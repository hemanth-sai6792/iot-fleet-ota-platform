"""Device-shadow reconciliation: diff desired vs. reported state.

Kept as pure functions (no I/O) so the interesting logic is unit-testable
without a broker or database — the async wrapper below just wires it up.
"""

import asyncio
import json
import logging
from typing import Any

import aiomqtt
import asyncpg

from app.config import MQTT_HOST, MQTT_PORT, RECONCILE_INTERVAL_SECONDS, TOPIC_DESIRED

logger = logging.getLogger("shadow")


def compute_delta(desired: dict[str, Any], reported: dict[str, Any]) -> dict[str, Any]:
    """Return the subset of `desired` keys whose value differs from `reported`.

    Empty dict means the device is in sync — nothing to push.
    """
    delta = {}
    for key, desired_value in desired.items():
        if reported.get(key) != desired_value:
            delta[key] = desired_value
    return delta


async def reconcile_device(
    pool: asyncpg.Pool, mqtt_client: aiomqtt.Client, device: asyncpg.Record
) -> None:
    delta = compute_delta(device["desired_state"], device["reported_state"])
    if not delta:
        return
    await mqtt_client.publish(
        TOPIC_DESIRED.format(device_id=device["id"]), json.dumps(delta)
    )
    logger.info("reconcile: pushed %s to device %s", delta, device["id"])


async def reconciliation_loop(pool: asyncpg.Pool, mqtt_client: aiomqtt.Client) -> None:
    """Background task: periodically re-checks every device for drift.

    Catches desired-state changes made through the API (e.g. a rollout)
    that arrived after the device's last reported-state message, so a
    silent device still eventually gets the command once it reconnects.
    """
    while True:
        rows = await pool.fetch(
            "SELECT id, desired_state, reported_state FROM devices"
        )
        for row in rows:
            await reconcile_device(pool, mqtt_client, row)
        await asyncio.sleep(RECONCILE_INTERVAL_SECONDS)
