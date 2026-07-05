"""Staged/canary OTA rollout engine.

Selection and health-evaluation are pure functions (unit-tested without a
database); the async functions below just wire them to Postgres + MQTT.
"""

import asyncio
import json
import logging
import random
from uuid import UUID

import aiomqtt
import asyncpg

from app.config import ROLLOUT_MIN_SAMPLE_SIZE, ROLLOUT_MONITOR_INTERVAL_SECONDS, TOPIC_DESIRED

logger = logging.getLogger("rollout")


def select_canary_devices(device_ids: list[str], canary_percent: int) -> list[str]:
    """Pick a random subset of the fleet for a staged rollout.

    Always at least 1 device (so a 1% canary on a small fleet still means
    something) and never more than the fleet size.
    """
    if not device_ids:
        return []
    count = max(1, round(len(device_ids) * canary_percent / 100))
    count = min(count, len(device_ids))
    return random.sample(device_ids, count)


def evaluate_rollout_health(
    applied: int, failed: int, pending: int, failure_threshold_percent: float
) -> bool:
    """Return True if the rollout should auto-rollback right now.

    Waits for ROLLOUT_MIN_SAMPLE_SIZE outcomes before trusting the failure
    rate — a single early failure in a 3-device canary is 33%, which would
    otherwise trip almost any reasonable threshold.
    """
    reported = applied + failed
    if reported < ROLLOUT_MIN_SAMPLE_SIZE:
        return False
    failure_rate = (failed / reported) * 100
    return failure_rate >= failure_threshold_percent


async def start_rollout(
    pool: asyncpg.Pool,
    mqtt_client: aiomqtt.Client,
    firmware_version: str,
    canary_percent: int,
    failure_threshold_percent: float,
) -> asyncpg.Record:
    devices = await pool.fetch("SELECT id, firmware_version FROM devices")
    if not devices:
        raise ValueError("no devices registered")

    previous_firmware_version = devices[0]["firmware_version"]
    target_ids = select_canary_devices([str(d["id"]) for d in devices], canary_percent)

    rollout = await pool.fetchrow(
        """
        INSERT INTO rollouts
            (firmware_version, previous_firmware_version, canary_percent,
             failure_threshold_percent, target_device_ids)
        VALUES ($1, $2, $3, $4, $5::uuid[])
        RETURNING *
        """,
        firmware_version,
        previous_firmware_version,
        canary_percent,
        failure_threshold_percent,
        target_ids,
    )
    await _push_firmware_to_devices(pool, mqtt_client, target_ids, firmware_version)
    logger.info(
        "rollout %s started: %s -> %s targeting %d/%d devices",
        rollout["id"], previous_firmware_version, firmware_version,
        len(target_ids), len(devices),
    )
    return rollout


async def _push_firmware_to_devices(
    pool: asyncpg.Pool, mqtt_client: aiomqtt.Client, device_ids: list[str], firmware_version: str
) -> None:
    for device_id in device_ids:
        await pool.execute(
            "UPDATE devices SET desired_state = desired_state || $2::jsonb WHERE id = $1",
            device_id,
            {"firmware_version": firmware_version},
        )
        await mqtt_client.publish(
            TOPIC_DESIRED.format(device_id=device_id),
            json.dumps({"firmware_version": firmware_version}),
        )


async def _rollout_progress(pool: asyncpg.Pool, rollout: asyncpg.Record) -> tuple[int, int, int, int]:
    total = len(rollout["target_device_ids"])
    counts = await pool.fetchrow(
        """
        SELECT
            count(*) FILTER (WHERE status = 'applied') AS applied,
            count(*) FILTER (WHERE status = 'failed') AS failed
        FROM rollout_events WHERE rollout_id = $1
        """,
        rollout["id"],
    )
    applied, failed = counts["applied"], counts["failed"]
    pending = total - applied - failed
    return applied, failed, pending, total


async def rollback_rollout(
    pool: asyncpg.Pool, mqtt_client: aiomqtt.Client, rollout: asyncpg.Record, manual: bool
) -> None:
    await _push_firmware_to_devices(
        pool, mqtt_client, rollout["target_device_ids"], rollout["previous_firmware_version"]
    )
    await pool.execute(
        "UPDATE rollouts SET status = $2, ended_at = now() WHERE id = $1",
        rollout["id"],
        "rolled_back_manual" if manual else "rolled_back",
    )
    logger.warning(
        "rollout %s rolled back (%s) to %s",
        rollout["id"], "manual" if manual else "auto-triggered", rollout["previous_firmware_version"],
    )


async def rollout_monitor_loop(pool: asyncpg.Pool, mqtt_client: aiomqtt.Client) -> None:
    while True:
        running = await pool.fetch("SELECT * FROM rollouts WHERE status = 'running'")
        for rollout in running:
            applied, failed, pending, total = await _rollout_progress(pool, rollout)
            if evaluate_rollout_health(applied, failed, pending, float(rollout["failure_threshold_percent"])):
                await rollback_rollout(pool, mqtt_client, rollout, manual=False)
            elif applied == total:
                await pool.execute(
                    "UPDATE rollouts SET status = 'completed', ended_at = now() WHERE id = $1",
                    rollout["id"],
                )
                logger.info("rollout %s completed successfully", rollout["id"])
        await asyncio.sleep(ROLLOUT_MONITOR_INTERVAL_SECONDS)
