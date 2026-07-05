"""Entrypoint for the core-engine container.

Everything here is logically separate (ingestion, shadow reconciliation,
rollout monitoring) but runs as one asyncio process for this demo — in a
production deployment these would scale independently, but one process
keeps a 1-day build tractable and still proves the async model works.
"""

import asyncio
import datetime
import logging

import aiomqtt

from app.config import MQTT_HOST, MQTT_PORT
from app.db import close_pool, init_pool
from app.ingestion import ingestion_loop, offline_sweep_loop
from app.rollout import rollout_monitor_loop
from app.shadow import reconciliation_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("engine")


async def partition_maintenance_loop(pool, interval_seconds: int = 3600) -> None:
    while True:
        tomorrow = datetime.date.today() + datetime.timedelta(days=1)
        await pool.execute("SELECT ensure_telemetry_partition($1)", tomorrow)
        await asyncio.sleep(interval_seconds)


async def main() -> None:
    pool = await init_pool()
    async with aiomqtt.Client(hostname=MQTT_HOST, port=MQTT_PORT) as publisher:
        logger.info("core-engine starting: ingestion, shadow, rollout monitor")
        try:
            await asyncio.gather(
                ingestion_loop(pool),
                offline_sweep_loop(pool),
                reconciliation_loop(pool, publisher),
                rollout_monitor_loop(pool, publisher),
                partition_maintenance_loop(pool),
            )
        finally:
            await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
