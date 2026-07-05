import asyncio
import contextlib
import logging
from uuid import UUID

import aiomqtt
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import MQTT_HOST, MQTT_PORT
from app.db import close_pool, get_pool, init_pool
from app.rollout import rollback_rollout, start_rollout
from app.schemas import DeviceCreate, DeviceOut, RolloutCreate, RolloutOut, RolloutProgress
from app.ws_manager import manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

app = FastAPI(title="IoT Fleet & OTA Management API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    _poller_task = asyncio.create_task(_fleet_poller())


@app.on_event("shutdown")
async def shutdown() -> None:
    if _poller_task:
        _poller_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _poller_task
    if _mqtt_cm:
        await _mqtt_cm.__aexit__(None, None, None)
    await close_pool()


async def _fleet_poller(interval_seconds: float = 1.5) -> None:
    """Pushes a fleet snapshot to every connected dashboard on a fixed tick.

    Simpler and easier to reason about than wiring Postgres LISTEN/NOTIFY
    for a dashboard that just needs "close to live," not sub-second push.
    """
    pool = get_pool()
    while True:
        devices = await pool.fetch(
            "SELECT id, name, status, firmware_version, last_seen FROM devices ORDER BY name"
        )
        rollouts = await pool.fetch(
            """
            SELECT r.id, r.firmware_version, r.status, r.target_device_ids,
                   coalesce(count(e.*) FILTER (WHERE e.status = 'applied'), 0) AS applied,
                   coalesce(count(e.*) FILTER (WHERE e.status = 'failed'), 0) AS failed
            FROM rollouts r
            LEFT JOIN rollout_events e ON e.rollout_id = r.id
            GROUP BY r.id
            ORDER BY r.started_at DESC LIMIT 10
            """
        )
        await manager.broadcast(
            {
                "type": "fleet_snapshot",
                "devices": [dict(d) for d in devices],
                "rollouts": [dict(r) for r in rollouts],
            }
        )
        await asyncio.sleep(interval_seconds)


@app.post("/devices", response_model=DeviceOut)
async def create_device(device: DeviceCreate):
    pool = get_pool()
    row = await pool.fetchrow(
        "INSERT INTO devices (name, model, firmware_version) VALUES ($1, $2, $3) RETURNING *",
        device.name,
        device.model,
        device.firmware_version,
    )
    return dict(row)


@app.get("/devices", response_model=list[DeviceOut])
async def list_devices():
    pool = get_pool()
    rows = await pool.fetch("SELECT * FROM devices ORDER BY name")
    return [dict(r) for r in rows]


@app.get("/devices/{device_id}", response_model=DeviceOut)
async def get_device(device_id: UUID):
    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM devices WHERE id = $1", device_id)
    if row is None:
        raise HTTPException(404, "device not found")
    return dict(row)


@app.post("/rollouts", response_model=RolloutOut)
async def create_rollout(rollout: RolloutCreate):
    pool = get_pool()
    try:
        row = await start_rollout(
            pool,
            mqtt_client(),
            rollout.firmware_version,
            rollout.canary_percent,
            rollout.failure_threshold_percent,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return dict(row)


@app.get("/rollouts", response_model=list[RolloutOut])
async def list_rollouts():
    pool = get_pool()
    rows = await pool.fetch("SELECT * FROM rollouts ORDER BY started_at DESC")
    return [dict(r) for r in rows]


@app.get("/rollouts/{rollout_id}", response_model=RolloutProgress)
async def get_rollout(rollout_id: UUID):
    pool = get_pool()
    rollout = await pool.fetchrow("SELECT * FROM rollouts WHERE id = $1", rollout_id)
    if rollout is None:
        raise HTTPException(404, "rollout not found")
    total = len(rollout["target_device_ids"])
    counts = await pool.fetchrow(
        """
        SELECT count(*) FILTER (WHERE status = 'applied') AS applied,
               count(*) FILTER (WHERE status = 'failed') AS failed
        FROM rollout_events WHERE rollout_id = $1
        """,
        rollout_id,
    )
    applied, failed = counts["applied"], counts["failed"]
    return {
        "rollout": dict(rollout),
        "applied": applied,
        "failed": failed,
        "pending": total - applied - failed,
        "total": total,
    }


@app.post("/rollouts/{rollout_id}/rollback", response_model=RolloutOut)
async def manual_rollback(rollout_id: UUID):
    pool = get_pool()
    rollout = await pool.fetchrow(
        "SELECT * FROM rollouts WHERE id = $1 AND status = 'running'", rollout_id
    )
    if rollout is None:
        raise HTTPException(404, "no running rollout with that id")
    await rollback_rollout(pool, mqtt_client(), rollout, manual=True)
    row = await pool.fetchrow("SELECT * FROM rollouts WHERE id = $1", rollout_id)
    return dict(row)


@app.websocket("/ws/fleet")
async def ws_fleet(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
