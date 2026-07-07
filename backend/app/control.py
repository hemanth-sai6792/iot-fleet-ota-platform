"""Application-layer services: the use-cases that sit between the API
routers and the domain/repository layers.

Every path that changes a device's desired state — a scene activation, a
rule firing, a unit/division cascade, an Alexa directive — funnels through
push_device_desired_state so there's exactly one place that touches MQTT.
"""

import json
import logging

import aiomqtt
import asyncpg

from app.config import TOPIC_DEVICE_DESIRED
from app.factory import CascadePlan, plan_cascade_command

logger = logging.getLogger("control")


async def push_device_desired_state(
    pool: asyncpg.Pool, mqtt_client: aiomqtt.Client, device_id: str, patch: dict
) -> None:
    await pool.execute(
        "UPDATE devices SET desired_state = desired_state || $2::jsonb WHERE id = $1",
        device_id,
        patch,
    )
    await mqtt_client.publish(TOPIC_DEVICE_DESIRED.format(device_id=device_id), json.dumps(patch))


async def activate_scene(pool: asyncpg.Pool, mqtt_client: aiomqtt.Client, scene_id: str) -> None:
    rows = await pool.fetch(
        "SELECT device_id, target_state FROM scene_devices WHERE scene_id = $1", scene_id
    )
    for row in rows:
        await push_device_desired_state(pool, mqtt_client, str(row["device_id"]), row["target_state"])


async def cascade_power(
    pool: asyncpg.Pool,
    mqtt_client: aiomqtt.Client,
    *,
    scope_type: str,
    scope_id: str,
    desired_power: str,
    force: bool,
    actor: str,
    reason: str | None,
) -> CascadePlan:
    """Turn a whole unit or division on/off, honoring the task-safety interlock."""
    scope_column = "u.id" if scope_type == "unit" else "dv.id"
    devices = await pool.fetch(
        f"""
        SELECT d.id, d.name, d.status, u.name AS unit_name, dv.name AS division_name, dv.site_id
        FROM devices d
        JOIN units u ON d.unit_id = u.id
        JOIN divisions dv ON u.division_id = dv.id
        WHERE {scope_column} = $1
        """,
        scope_id,
    )
    if not devices:
        return CascadePlan()

    had_busy_devices = any(d["status"] == "running_task" for d in devices)
    plan = plan_cascade_command([dict(d) for d in devices], force=force)
    for device_id in plan.to_command:
        await push_device_desired_state(pool, mqtt_client, device_id, {"power": desired_power})

    table = "units" if scope_type == "unit" else "divisions"
    await pool.execute(
        f"UPDATE {table} SET desired_state = desired_state || $2::jsonb WHERE id = $1",
        scope_id,
        {"power": desired_power},
    )

    site_id = devices[0]["site_id"]
    forced_note = " (forced past busy devices)" if force and had_busy_devices else ""
    await pool.execute(
        """
        INSERT INTO audit_log (actor, site_id, action, target_type, target_id, reason)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        actor,
        site_id,
        f"power_{desired_power}{forced_note}",
        scope_type,
        scope_id,
        reason,
    )
    return plan
