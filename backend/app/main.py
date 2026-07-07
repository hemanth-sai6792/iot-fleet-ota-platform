import asyncio
import contextlib
import logging
from datetime import datetime
from uuid import UUID

import aiomqtt
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.alexa import build_discovery_response, handle_directive
from app.config import MQTT_HOST, MQTT_PORT
from app.control import activate_scene, cascade_power, push_device_desired_state
from app.db import close_pool, get_pool, init_pool
from app.household import evaluate_rule, validate_alexa_name
from app.schemas import (
    AuditLogOut,
    DesiredStatePatch,
    DeviceCreate,
    DeviceOut,
    DivisionCreate,
    DivisionOut,
    FaultLogOut,
    MeterReconciliationOut,
    PowerRequest,
    PowerResponse,
    RoomCreate,
    RoomOut,
    RuleCreate,
    RuleEvaluateRequest,
    RuleOut,
    SceneCreate,
    SceneOut,
    SiteCreate,
    SiteOut,
    ThresholdAlertOut,
    UnitCreate,
    UnitOut,
)
from app.ws_manager import manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

app = FastAPI(title="Home Automation Platform API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_mqtt_client: aiomqtt.Client | None = None
_mqtt_cm = None
_poller_task: asyncio.Task | None = None


def mqtt_client() -> aiomqtt.Client:
    assert _mqtt_client is not None
    return _mqtt_client


@app.on_event("startup")
async def startup() -> None:
    global _mqtt_client, _mqtt_cm, _poller_task
    await init_pool()
    _mqtt_cm = aiomqtt.Client(hostname=MQTT_HOST, port=MQTT_PORT)
    _mqtt_client = await _mqtt_cm.__aenter__()
    _poller_task = asyncio.create_task(_live_poller())


@app.on_event("shutdown")
async def shutdown() -> None:
    if _poller_task:
        _poller_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _poller_task
    if _mqtt_cm:
        await _mqtt_cm.__aexit__(None, None, None)
    await close_pool()


async def _live_poller(interval_seconds: float = 1.5) -> None:
    pool = get_pool()
    while True:
        devices = await pool.fetch(
            "SELECT id, site_id, name, status, room_id, unit_id, last_seen FROM devices ORDER BY name"
        )
        units = await pool.fetch("SELECT id, division_id, name, desired_state FROM units ORDER BY name")
        divisions = await pool.fetch("SELECT id, site_id, name, desired_state FROM divisions ORDER BY name")
        alerts = await pool.fetch("SELECT id, scope_type, scope_id, threshold_kw FROM threshold_alerts WHERE status = 'active'")
        await manager.broadcast(
            {
                "type": "live_snapshot",
                "devices": [dict(d) for d in devices],
                "units": [dict(u) for u in units],
                "divisions": [dict(d) for d in divisions],
                "active_alerts": [dict(a) for a in alerts],
            }
        )
        await asyncio.sleep(interval_seconds)


async def _require_site_type(pool, site_id: UUID, allowed: tuple[str, ...]) -> str:
    row = await pool.fetchrow("SELECT type FROM sites WHERE id = $1", site_id)
    if row is None:
        raise HTTPException(404, "site not found")
    if row["type"] not in allowed:
        raise HTTPException(400, f"site type '{row['type']}' does not support this resource")
    return row["type"]


# ---------- Sites ----------

@app.post("/sites", response_model=SiteOut)
async def create_site(site: SiteCreate):
    pool = get_pool()
    row = await pool.fetchrow(
        "INSERT INTO sites (name, type) VALUES ($1, $2) RETURNING *", site.name, site.type
    )
    return dict(row)


@app.get("/sites", response_model=list[SiteOut])
async def list_sites():
    pool = get_pool()
    rows = await pool.fetch("SELECT * FROM sites ORDER BY name")
    return [dict(r) for r in rows]


# ---------- Household: rooms, devices, scenes, rules ----------

@app.post("/rooms", response_model=RoomOut)
async def create_room(room: RoomCreate):
    pool = get_pool()
    await _require_site_type(pool, room.site_id, ("household", "showroom"))
    errors = validate_alexa_name(room.name)
    if errors:
        raise HTTPException(400, {"errors": errors})
    row = await pool.fetchrow(
        "INSERT INTO rooms (site_id, name) VALUES ($1, $2) RETURNING *", room.site_id, room.name
    )
    return dict(row)


@app.get("/rooms", response_model=list[RoomOut])
async def list_rooms(site_id: UUID):
    pool = get_pool()
    rows = await pool.fetch("SELECT * FROM rooms WHERE site_id = $1 ORDER BY name", site_id)
    return [dict(r) for r in rows]


@app.post("/devices", response_model=DeviceOut)
async def create_device(device: DeviceCreate):
    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO devices (site_id, name, device_type, room_id, unit_id, task_interruptible)
        VALUES ($1, $2, $3, $4, $5, $6) RETURNING *
        """,
        device.site_id, device.name, device.device_type, device.room_id, device.unit_id,
        device.task_interruptible,
    )
    return dict(row)


@app.get("/devices", response_model=list[DeviceOut])
async def list_devices(site_id: UUID | None = None, room_id: UUID | None = None, unit_id: UUID | None = None):
    pool = get_pool()
    conditions, args = [], []
    for i, (col, val) in enumerate([("site_id", site_id), ("room_id", room_id), ("unit_id", unit_id)], start=1):
        if val is not None:
            conditions.append(f"{col} = ${len(args) + 1}")
            args.append(val)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = await pool.fetch(f"SELECT * FROM devices {where} ORDER BY name", *args)
    return [dict(r) for r in rows]


@app.patch("/devices/{device_id}/desired-state", response_model=DeviceOut)
async def patch_device_desired_state(device_id: UUID, body: DesiredStatePatch):
    pool = get_pool()
    await push_device_desired_state(pool, mqtt_client(), str(device_id), body.patch)
    row = await pool.fetchrow("SELECT * FROM devices WHERE id = $1", device_id)
    if row is None:
        raise HTTPException(404, "device not found")
    return dict(row)


@app.post("/scenes", response_model=SceneOut)
async def create_scene(scene: SceneCreate):
    pool = get_pool()
    await _require_site_type(pool, scene.site_id, ("household", "showroom"))
    errors = validate_alexa_name(scene.name)
    if errors:
        raise HTTPException(400, {"errors": errors})
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "INSERT INTO scenes (site_id, name) VALUES ($1, $2) RETURNING *", scene.site_id, scene.name
            )
            for sd in scene.devices:
                await conn.execute(
                    "INSERT INTO scene_devices (scene_id, device_id, target_state) VALUES ($1, $2, $3)",
                    row["id"], sd.device_id, sd.target_state,
                )
    return dict(row)


@app.get("/scenes", response_model=list[SceneOut])
async def list_scenes(site_id: UUID):
    pool = get_pool()
    rows = await pool.fetch("SELECT * FROM scenes WHERE site_id = $1 ORDER BY name", site_id)
    return [dict(r) for r in rows]


@app.post("/scenes/{scene_id}/activate")
async def activate_scene_endpoint(scene_id: UUID):
    pool = get_pool()
    await activate_scene(pool, mqtt_client(), str(scene_id))
    return {"status": "activated"}


@app.post("/rules", response_model=RuleOut)
async def create_rule(rule: RuleCreate):
    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO rules (site_id, name, trigger_type, trigger_config, action_type, action_target_id, enabled)
        VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *
        """,
        rule.site_id, rule.name, rule.trigger_type, rule.trigger_config, rule.action_type,
        rule.action_target_id, rule.enabled,
    )
    return dict(row)


@app.get("/rules", response_model=list[RuleOut])
async def list_rules(site_id: UUID):
    pool = get_pool()
    rows = await pool.fetch("SELECT * FROM rules WHERE site_id = $1 ORDER BY name", site_id)
    return [dict(r) for r in rows]


@app.post("/rules/{rule_id}/evaluate")
async def evaluate_rule_endpoint(rule_id: UUID, body: RuleEvaluateRequest):
    pool = get_pool()
    rule = await pool.fetchrow("SELECT * FROM rules WHERE id = $1 AND enabled", rule_id)
    if rule is None:
        raise HTTPException(404, "rule not found or disabled")
    fired = evaluate_rule(
        dict(rule), now=datetime.now(), reported_state=body.reported_state, spoken_phrase=body.spoken_phrase
    )
    if fired:
        if rule["action_type"] == "scene":
            await activate_scene(pool, mqtt_client(), str(rule["action_target_id"]))
        else:
            await push_device_desired_state(pool, mqtt_client(), str(rule["action_target_id"]), {"power": "on"})
    return {"fired": fired}


# ---------- Factory: divisions, units, cascading power, usage ----------

@app.post("/divisions", response_model=DivisionOut)
async def create_division(division: DivisionCreate):
    pool = get_pool()
    await _require_site_type(pool, division.site_id, ("factory",))
    row = await pool.fetchrow(
        "INSERT INTO divisions (site_id, name, alert_threshold_kw) VALUES ($1, $2, $3) RETURNING *",
        division.site_id, division.name, division.alert_threshold_kw,
    )
    return dict(row)


@app.get("/divisions", response_model=list[DivisionOut])
async def list_divisions(site_id: UUID):
    pool = get_pool()
    rows = await pool.fetch("SELECT * FROM divisions WHERE site_id = $1 ORDER BY name", site_id)
    return [dict(r) for r in rows]


@app.post("/units", response_model=UnitOut)
async def create_unit(unit: UnitCreate):
    pool = get_pool()
    row = await pool.fetchrow(
        "INSERT INTO units (division_id, name, alert_threshold_kw) VALUES ($1, $2, $3) RETURNING *",
        unit.division_id, unit.name, unit.alert_threshold_kw,
    )
    return dict(row)


@app.get("/units", response_model=list[UnitOut])
async def list_units(division_id: UUID):
    pool = get_pool()
    rows = await pool.fetch("SELECT * FROM units WHERE division_id = $1 ORDER BY name", division_id)
    return [dict(r) for r in rows]


def _power_response(plan) -> PowerResponse:
    return PowerResponse(
        commanded_device_ids=[UUID(d) for d in plan.to_command],
        blocked=[
            {
                "device_id": b.device_id,
                "device_name": b.device_name,
                "unit_name": b.unit_name,
                "division_name": b.division_name,
                "message": b.message,
            }
            for b in plan.blocked
        ],
    )


@app.post("/units/{unit_id}/power", response_model=PowerResponse)
async def unit_power(unit_id: UUID, body: PowerRequest):
    pool = get_pool()
    if body.cross_site and not body.reason:
        raise HTTPException(400, "reason is required for cross-site remote actions")
    plan = await cascade_power(
        pool, mqtt_client(), scope_type="unit", scope_id=str(unit_id), desired_power=body.desired_power,
        force=body.force, actor=body.actor, reason=body.reason,
    )
    return _power_response(plan)


@app.post("/divisions/{division_id}/power", response_model=PowerResponse)
async def division_power(division_id: UUID, body: PowerRequest):
    pool = get_pool()
    if body.cross_site and not body.reason:
        raise HTTPException(400, "reason is required for cross-site remote actions")
    plan = await cascade_power(
        pool, mqtt_client(), scope_type="division", scope_id=str(division_id), desired_power=body.desired_power,
        force=body.force, actor=body.actor, reason=body.reason,
    )
    return _power_response(plan)


@app.get("/units/{unit_id}/usage")
async def unit_usage(unit_id: UUID, limit: int = 100):
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT ts, kwh FROM usage_readings WHERE scope_type = 'unit' AND scope_id = $1 ORDER BY ts DESC LIMIT $2",
        unit_id, limit,
    )
    return [dict(r) for r in rows]


@app.get("/divisions/{division_id}/usage")
async def division_usage(division_id: UUID, limit: int = 100):
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT ts, kwh FROM usage_readings WHERE scope_type = 'division' AND scope_id = $1 ORDER BY ts DESC LIMIT $2",
        division_id, limit,
    )
    return [dict(r) for r in rows]


@app.get("/divisions/{division_id}/reconciliations", response_model=list[MeterReconciliationOut])
async def division_reconciliations(division_id: UUID, limit: int = 20):
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT * FROM meter_reconciliations WHERE division_id = $1 ORDER BY ts DESC LIMIT $2",
        division_id, limit,
    )
    return [dict(r) for r in rows]


@app.get("/alerts", response_model=list[ThresholdAlertOut])
async def list_alerts(status: str = "active"):
    pool = get_pool()
    rows = await pool.fetch("SELECT * FROM threshold_alerts WHERE status = $1 ORDER BY triggered_at DESC", status)
    return [dict(r) for r in rows]


@app.get("/faults", response_model=list[FaultLogOut])
async def list_faults(device_id: UUID | None = None, limit: int = 100):
    pool = get_pool()
    if device_id:
        rows = await pool.fetch(
            "SELECT * FROM fault_logs WHERE device_id = $1 ORDER BY ts DESC LIMIT $2", device_id, limit
        )
    else:
        rows = await pool.fetch("SELECT * FROM fault_logs ORDER BY ts DESC LIMIT $1", limit)
    return [dict(r) for r in rows]


# ---------- Audit ----------

@app.get("/audit", response_model=list[AuditLogOut])
async def list_audit(site_id: UUID, limit: int = 100):
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT * FROM audit_log WHERE site_id = $1 ORDER BY ts DESC LIMIT $2", site_id, limit
    )
    return [dict(r) for r in rows]


# ---------- Alexa (household/showroom only) ----------

@app.get("/alexa/discovery")
async def alexa_discovery(site_id: UUID):
    pool = get_pool()
    rows = await pool.fetch("SELECT * FROM devices WHERE site_id = $1", site_id)
    return build_discovery_response([dict(r) for r in rows])


@app.post("/alexa/directive")
async def alexa_directive(directive: dict):
    pool = get_pool()
    command = handle_directive(directive)
    if command["target_type"] == "device":
        await push_device_desired_state(pool, mqtt_client(), command["target_id"], command["desired_state"])
    else:
        await activate_scene(pool, mqtt_client(), command["target_id"])
    return {"status": "accepted"}


# ---------- Live WebSocket ----------

@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
