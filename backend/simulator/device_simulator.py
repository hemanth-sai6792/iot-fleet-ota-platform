"""Spawns N virtual devices as concurrent asyncio tasks over MQTT.

This is the answer to "how did you test a fleet without owning real
hardware": each virtual device is just an aiomqtt session publishing
heartbeats/telemetry and reacting to desired-state commands, so the
ingestion path and rollout engine get exercised at real (if modest) scale.
"""

import asyncio
import json
import logging
import os
import random

import aiomqtt
import httpx

API_URL = os.environ.get("API_URL", "http://localhost:8000")
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
DEVICE_COUNT = int(os.environ.get("DEVICE_COUNT", "25"))
# probability a given OTA update fails on a device — crank this up to demo
# the rollout engine's auto-rollback (e.g. FAILURE_RATE=0.6)
FAILURE_RATE = float(os.environ.get("FAILURE_RATE", "0.1"))
HEARTBEAT_INTERVAL = 5
TELEMETRY_INTERVAL = 8

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("simulator")


async def register_devices() -> list[dict]:
    async with httpx.AsyncClient() as client:
        for attempt in range(30):
            try:
                resp = await client.get(f"{API_URL}/devices", timeout=5)
                resp.raise_for_status()
                break
            except httpx.HTTPError:
                logger.info("waiting for API... (%d/30)", attempt + 1)
                await asyncio.sleep(2)
        else:
            raise RuntimeError("API never became available")

        devices = []
        for i in range(DEVICE_COUNT):
            resp = await client.post(
                f"{API_URL}/devices",
                json={"name": f"sensor-{i:03d}", "model": "temp-humidity-v2"},
            )
            resp.raise_for_status()
            devices.append(resp.json())
        return devices


async def run_device(device: dict) -> None:
    device_id = device["id"]
    firmware_version = device["firmware_version"]
    desired_topic = f"devices/{device_id}/state/desired"
    reported_topic = f"devices/{device_id}/state/reported"
    heartbeat_topic = f"devices/{device_id}/heartbeat"

    async with aiomqtt.Client(hostname=MQTT_HOST, port=MQTT_PORT) as client:
        await client.subscribe(desired_topic)

        async def listen_for_commands():
            nonlocal firmware_version
            async for message in client.messages:
                command = json.loads(message.payload)
                target_version = command.get("firmware_version")
                if target_version and target_version != firmware_version:
                    await asyncio.sleep(random.uniform(1, 4))  # simulate download+flash
                    if random.random() < FAILURE_RATE:
                        logger.warning("%s: OTA to %s FAILED", device["name"], target_version)
                        await client.publish(
                            reported_topic,
                            json.dumps(
                                {"firmware_version": firmware_version, "update_status": "failed"}
                            ),
                        )
                    else:
                        firmware_version = target_version
                        logger.info("%s: OTA to %s applied", device["name"], target_version)
                        await client.publish(
                            reported_topic,
                            json.dumps(
                                {"firmware_version": firmware_version, "update_status": "applied"}
                            ),
                        )

        async def heartbeat_and_telemetry():
            tick = 0
            while True:
                await client.publish(heartbeat_topic, json.dumps({"ts": tick}))
                if tick % TELEMETRY_INTERVAL == 0:
                    await client.publish(
                        reported_topic,
                        json.dumps(
                            {
                                "firmware_version": firmware_version,
                                "temperature_c": round(random.uniform(18, 26), 1),
                                "humidity_pct": round(random.uniform(30, 60), 1),
                            }
                        ),
                    )
                tick += HEARTBEAT_INTERVAL
                await asyncio.sleep(HEARTBEAT_INTERVAL)

        await asyncio.gather(listen_for_commands(), heartbeat_and_telemetry())


async def main() -> None:
    devices = await register_devices()
    logger.info("registered %d virtual devices, starting simulation", len(devices))
    await asyncio.gather(*(run_device(d) for d in devices))


if __name__ == "__main__":
    asyncio.run(main())
