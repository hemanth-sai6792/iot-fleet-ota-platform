"""Bootstraps a sample household site and a sample factory site over the
API, then simulates every device/meter as a concurrent asyncio/MQTT client.

This is how the ingestion path, cascade control, and usage monitoring get
exercised at all without owning a house full of smart switches or an actual
factory floor.
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
HEARTBEAT_INTERVAL = 5
USAGE_INTERVAL = 8

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("simulator")


async def _wait_for_api(client: httpx.AsyncClient) -> None:
    for attempt in range(30):
        try:
            resp = await client.get(f"{API_URL}/sites", timeout=5)
            resp.raise_for_status()
            return
        except httpx.HTTPError:
            logger.info("waiting for API... (%d/30)", attempt + 1)
            await asyncio.sleep(2)
    raise RuntimeError("API never became available")


async def bootstrap(client: httpx.AsyncClient) -> dict:
    household_site = (await client.post(f"{API_URL}/sites", json={"name": "Sample Household", "type": "household"})).json()
    rooms = {
        name: (await client.post(f"{API_URL}/rooms", json={"site_id": household_site["id"], "name": name})).json()
        for name in ["Living Room", "Kitchen", "Bedroom"]
    }
    household_devices = []
    for name, device_type, room in [
        ("Living Room Lamp", "switch", "Living Room"),
        ("Kitchen Lights", "dimmer", "Kitchen"),
        ("Bedroom Thermostat", "thermostat", "Bedroom"),
        ("Front Door Lock", "lock", "Living Room"),
    ]:
        device = (await client.post(
            f"{API_URL}/devices",
            json={
                "site_id": household_site["id"], "name": name, "device_type": device_type,
                "room_id": rooms[room]["id"],
            },
        )).json()
        household_devices.append(device)

    factory_site = (await client.post(f"{API_URL}/sites", json={"name": "Sample Factory", "type": "factory"})).json()
    division = (await client.post(
        f"{API_URL}/divisions",
        json={"site_id": factory_site["id"], "name": "Assembly Wing", "alert_threshold_kw": 500},
    )).json()

    factory_devices = []
    unit_specs = [
        ("Assembly Line 1", [("Conveyor motor", "motor", True), ("Robotic welder", "welder", False), ("Line lighting", "lighting", True)]),
        ("Assembly Line 2", [("Conveyor motor", "motor", True), ("Press machine", "press", False), ("Line lighting", "lighting", True)]),
    ]
    units = []
    for unit_name, devices in unit_specs:
        unit = (await client.post(
            f"{API_URL}/units",
            json={"division_id": division["id"], "name": unit_name, "alert_threshold_kw": 250},
        )).json()
        units.append(unit)
        for device_name, device_type, interruptible in devices:
            device = (await client.post(
                f"{API_URL}/devices",
                json={
                    "site_id": factory_site["id"], "name": device_name, "device_type": device_type,
                    "unit_id": unit["id"], "task_interruptible": interruptible,
                },
            )).json()
            factory_devices.append(device)

    return {"household_devices": household_devices, "factory_devices": factory_devices, "units": units, "division": division}


async def run_household_device(device: dict) -> None:
    device_id, name, device_type = device["id"], device["name"], device["device_type"]
    desired_topic = f"devices/{device_id}/state/desired"
    reported_topic = f"devices/{device_id}/state/reported"
    heartbeat_topic = f"devices/{device_id}/heartbeat"
    power = "off"

    async with aiomqtt.Client(hostname=MQTT_HOST, port=MQTT_PORT) as client:
        await client.subscribe(desired_topic)

        async def listen():
            nonlocal power
            async for message in client.messages:
                patch = json.loads(message.payload)
                if "power" in patch:
                    power = patch["power"]
                    logger.info("%s: power -> %s", name, power)
                await client.publish(reported_topic, json.dumps({"state": patch}))

        async def heartbeat():
            while True:
                await client.publish(heartbeat_topic, json.dumps({}))
                state = {"power": power}
                if device_type == "thermostat":
                    state["temperature_c"] = round(random.uniform(19, 24), 1)
                await client.publish(reported_topic, json.dumps({"state": state}))
                await asyncio.sleep(HEARTBEAT_INTERVAL)

        await asyncio.gather(listen(), heartbeat())


async def run_factory_device(device: dict) -> None:
    device_id, name = device["id"], device["name"]
    interruptible = device["task_interruptible"]
    desired_topic = f"devices/{device_id}/state/desired"
    reported_topic = f"devices/{device_id}/state/reported"
    heartbeat_topic = f"devices/{device_id}/heartbeat"
    power = "on"
    busy = False

    async with aiomqtt.Client(hostname=MQTT_HOST, port=MQTT_PORT) as client:
        await client.subscribe(desired_topic)

        async def listen():
            nonlocal power
            async for message in client.messages:
                patch = json.loads(message.payload)
                if "power" in patch:
                    power = patch["power"]
                    logger.info("%s: power -> %s", name, power)
                await client.publish(reported_topic, json.dumps({"state": patch}))

        async def heartbeat():
            nonlocal busy
            while True:
                await client.publish(heartbeat_topic, json.dumps({}))
                # non-interruptible machines occasionally enter a task they
                # can't be safely stopped mid-way through — this is exactly
                # what the cascade interlock has to detect and block on.
                if not interruptible and power == "on":
                    busy = random.random() < 0.3
                else:
                    busy = False
                await client.publish(reported_topic, json.dumps({"state": {"power": power}, "busy": busy}))
                await asyncio.sleep(HEARTBEAT_INTERVAL)

        await asyncio.gather(listen(), heartbeat())


async def run_unit_meter(unit: dict, baseline_kw: float) -> None:
    topic = f"units/{unit['id']}/usage"
    async with aiomqtt.Client(hostname=MQTT_HOST, port=MQTT_PORT) as client:
        while True:
            kwh = round(baseline_kw + random.uniform(-5, 5), 2)
            await client.publish(topic, json.dumps({"kwh": kwh}))
            await asyncio.sleep(USAGE_INTERVAL)


async def run_division_meter(division: dict, unit_baselines: list[float]) -> None:
    topic = f"divisions/{division['id']}/usage"
    async with aiomqtt.Client(hostname=MQTT_HOST, port=MQTT_PORT) as client:
        while True:
            # small noise most of the time; an occasional bigger gap
            # demonstrates the meter-reconciliation flag actually firing
            noise = random.uniform(-3, 3) if random.random() > 0.15 else random.uniform(30, 60)
            kwh = round(sum(unit_baselines) + noise, 2)
            await client.publish(topic, json.dumps({"kwh": kwh}))
            await asyncio.sleep(USAGE_INTERVAL)


async def main() -> None:
    async with httpx.AsyncClient() as client:
        await _wait_for_api(client)
        data = await bootstrap(client)

    logger.info(
        "bootstrapped %d household devices, %d factory devices",
        len(data["household_devices"]), len(data["factory_devices"]),
    )

    unit_baselines = [random.uniform(80, 150) for _ in data["units"]]

    tasks = (
        [run_household_device(d) for d in data["household_devices"]]
        + [run_factory_device(d) for d in data["factory_devices"]]
        + [run_unit_meter(u, baseline) for u, baseline in zip(data["units"], unit_baselines)]
        + [run_division_meter(data["division"], unit_baselines)]
    )
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
