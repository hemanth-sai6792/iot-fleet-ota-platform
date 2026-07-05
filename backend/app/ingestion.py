"""Async MQTT ingestion: the hot path this whole project exists to exercise.

One long-lived aiomqtt session subscribes to every device's reported-state
and heartbeat topics. Each message does a small, bounded amount of work
(one upsert, one insert, maybe one rollout-event insert) so the loop never
blocks on anything slow — that's the property SonarQube/the concurrency
review is meant to catch regressions in.
"""

import asyncio
import json
import logging

import aiomqtt
import asyncpg

from app.config import (
    MQTT_HOST,
    MQTT_PORT,
    TOPIC_HEARTBEAT_WILDCARD,
    TOPIC_REPORTED_WILDCARD,
)

logger = logging.getLogger("ingestion")


def _device_id_from_topic(topic: str) -> str:
    # devices/{id}/state/reported -> {id}; devices/{id}/heartbeat -> {id}
    return topic.split("/")[1]


async def _handle_reported(pool: asyncpg.Pool, device_id: str, payload: dict) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO telemetry (device_id, payload) VALUES ($1, $2)",
                device_id,
                payload,
            )
            update_status = payload.pop("update_status", None)
            row = await conn.fetchrow(
                """
                UPDATE devices
                SET reported_state = reported_state || $2::jsonb,
                    firmware_version = COALESCE($3, firmware_version),
                    status = 'online',
                    last_seen = now()
                WHERE id = $1
                RETURNING id
                """,
                device_id,
                payload,
                payload.get("firmware_version"),
            )
            if row is None:
                logger.warning("reported state for unknown device %s", device_id)
                return

            if update_status in ("applied", "failed"):
                rollout = await conn.fetchrow(
                    """
                    SELECT id FROM rollouts
                    WHERE status = 'running' AND $1 = ANY(target_device_ids)
                    ORDER BY started_at DESC LIMIT 1
                    """,
                    device_id,
                )
                if rollout is not None:
                    await conn.execute(
                        """
                        INSERT INTO rollout_events (rollout_id, device_id, status)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (rollout_id, device_id) DO UPDATE SET status = $3, ts = now()
                        """,
                        rollout["id"],
                        device_id,
                        update_status,
                    )


async def _handle_heartbeat(pool: asyncpg.Pool, device_id: str) -> None:
    await pool.execute(
        "UPDATE devices SET status = 'online', last_seen = now() WHERE id = $1",
        device_id,
    )


async def ingestion_loop(pool: asyncpg.Pool) -> None:
    async with aiomqtt.Client(hostname=MQTT_HOST, port=MQTT_PORT) as client:
        await client.subscribe(TOPIC_REPORTED_WILDCARD)
        await client.subscribe(TOPIC_HEARTBEAT_WILDCARD)
        logger.info("ingestion loop subscribed, listening for device messages")
        async for message in client.messages:
            try:
                topic = str(message.topic)
                device_id = _device_id_from_topic(topic)
                if topic.endswith("/heartbeat"):
                    await _handle_heartbeat(pool, device_id)
                else:
                    payload = json.loads(message.payload)
                    await _handle_reported(pool, device_id, payload)
            except Exception:
                # one malformed/unexpected message must never kill the loop —
                # thousands of other devices are still publishing on this connection
                logger.exception("failed to process message on %s", message.topic)


async def offline_sweep_loop(pool: asyncpg.Pool, interval_seconds: int = 10) -> None:
    """Marks devices offline if they haven't reported in a while.

    Runs alongside ingestion since a dead connection never sends a "going
    offline" message — absence has to be detected, not received.
    """
    from app.config import OFFLINE_AFTER_SECONDS

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
