"""Async MQTT ingestion: the hot path this whole project exists to exercise.

One long-lived aiomqtt session subscribes to every device's reported-state
and heartbeat topics, plus unit/division meter readings. Each message does a
small, bounded amount of work so the loop never blocks on anything slow —
that's the property SonarQube/the concurrency review is meant to catch
regressions in.
"""

import asyncio
import json
import logging

import aiomqtt
import asyncpg

from app.config import (
    MQTT_HOST,
    MQTT_PORT,
    OFFLINE_AFTER_SECONDS,
    TOPIC_DEVICE_HEARTBEAT_WILDCARD,
    TOPIC_DEVICE_REPORTED_WILDCARD,
    TOPIC_DIVISION_USAGE_WILDCARD,
    TOPIC_UNIT_USAGE_WILDCARD,
)

logger = logging.getLogger("ingestion")


def _id_from_topic(topic: str) -> str:
    # devices/{id}/state/reported, devices/{id}/heartbeat,
    # units/{id}/usage, divisions/{id}/usage -> {id} is always segment 1
    return topic.split("/")[1]


async def _handle_device_reported(pool: asyncpg.Pool, device_id: str, payload: dict) -> None:
    state = payload.get("state", {})
    busy = payload.get("busy", False)
    fault = payload.get("fault")

    status = "fault" if fault else ("running_task" if busy else "online")

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                UPDATE devices
                SET reported_state = reported_state || $2::jsonb,
                    status = $3,
                    last_seen = now()
                WHERE id = $1
                RETURNING id
                """,
                device_id,
                state,
                status,
            )
            if row is None:
                logger.warning("reported state for unknown device %s", device_id)
                return
            if fault:
                await conn.execute(
                    "INSERT INTO fault_logs (device_id, code, message) VALUES ($1, $2, $3)",
                    device_id,
                    fault.get("code", "unknown"),
                    fault.get("message", ""),
                )


async def _handle_device_heartbeat(pool: asyncpg.Pool, device_id: str) -> None:
    # A heartbeat only proves liveness, not an idle/busy transition — don't
    # downgrade a device that's mid-task back to "online" just because it
    # pinged in.
    await pool.execute(
        """
        UPDATE devices SET status = 'online', last_seen = now()
        WHERE id = $1 AND status = 'offline'
        """,
        device_id,
    )
    await pool.execute("UPDATE devices SET last_seen = now() WHERE id = $1", device_id)


async def _handle_usage(pool: asyncpg.Pool, scope_type: str, scope_id: str, payload: dict) -> None:
    kwh = payload.get("kwh")
    if kwh is None:
        return
    await pool.execute(
        "INSERT INTO usage_readings (scope_type, scope_id, kwh) VALUES ($1, $2, $3)",
        scope_type,
        scope_id,
        kwh,
    )


async def ingestion_loop(pool: asyncpg.Pool) -> None:
    async with aiomqtt.Client(hostname=MQTT_HOST, port=MQTT_PORT) as client:
        await client.subscribe(TOPIC_DEVICE_REPORTED_WILDCARD)
        await client.subscribe(TOPIC_DEVICE_HEARTBEAT_WILDCARD)
        await client.subscribe(TOPIC_UNIT_USAGE_WILDCARD)
        await client.subscribe(TOPIC_DIVISION_USAGE_WILDCARD)
        logger.info("ingestion loop subscribed, listening for device and meter messages")
        async for message in client.messages:
            try:
                topic = str(message.topic)
                entity_id = _id_from_topic(topic)
                if topic.endswith("/heartbeat"):
                    await _handle_device_heartbeat(pool, entity_id)
                elif topic.endswith("/state/reported"):
                    await _handle_device_reported(pool, entity_id, json.loads(message.payload))
                elif topic.startswith("units/") and topic.endswith("/usage"):
                    await _handle_usage(pool, "unit", entity_id, json.loads(message.payload))
                elif topic.startswith("divisions/") and topic.endswith("/usage"):
                    await _handle_usage(pool, "division", entity_id, json.loads(message.payload))
            except Exception:
                # one malformed/unexpected message must never kill the loop —
                # every other device/meter is still publishing on this connection
                logger.exception("failed to process message on %s", message.topic)


async def offline_sweep_loop(pool: asyncpg.Pool, interval_seconds: int = 10) -> None:
    """Marks devices offline if they haven't reported in a while.

    Runs alongside ingestion since a dead connection never sends a "going
    offline" message — absence has to be detected, not received.
    """
    while True:
        await pool.execute(
            """
            UPDATE devices SET status = 'offline'
            WHERE status != 'offline'
              AND last_seen < now() - ($1 || ' seconds')::interval
            """,
            str(OFFLINE_AFTER_SECONDS),
        )
        await asyncio.sleep(interval_seconds)
