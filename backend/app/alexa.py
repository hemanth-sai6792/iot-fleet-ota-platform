"""Alexa Smart Home adapter — translates between our internal device model
and Alexa's discovery/directive shapes.

This is a stub: a real integration needs an Alexa Smart Home Skill, Login
with Amazon account linking, and an AWS Lambda endpoint. What's real here is
the boundary — nothing in household.py or the database schema knows Alexa's
payload shapes, only this module does. Household/showroom sites only;
factory sites have no voice control.
"""

from typing import Any

# Our device_type -> Alexa's displayCategories + supported interface.
# Extend this table for new device types; nothing else needs to change.
_DEVICE_TYPE_TO_ALEXA = {
    "switch": {"displayCategories": ["SWITCH"], "interface": "Alexa.PowerController"},
    "dimmer": {"displayCategories": ["LIGHT"], "interface": "Alexa.PowerController"},
    "thermostat": {"displayCategories": ["THERMOSTAT"], "interface": "Alexa.ThermostatController"},
    "lock": {"displayCategories": ["SMARTLOCK"], "interface": "Alexa.LockController"},
}


def build_discovery_response(devices: list[dict[str, Any]]) -> dict[str, Any]:
    """Build an Alexa Discover.Response payload from our device rows."""
    endpoints = []
    for device in devices:
        mapping = _DEVICE_TYPE_TO_ALEXA.get(device["device_type"])
        if mapping is None:
            continue  # unsupported device type simply isn't voice-discoverable
        endpoints.append(
            {
                "endpointId": str(device["id"]),
                "friendlyName": device["name"],
                "displayCategories": mapping["displayCategories"],
                "capabilities": [{"interface": mapping["interface"]}],
            }
        )
    return {"event": {"header": {"name": "Discover.Response"}, "payload": {"endpoints": endpoints}}}


def handle_directive(directive: dict[str, Any]) -> dict[str, Any]:
    """Translate an incoming Alexa directive into an internal command.

    Returns {"target_type": "device"|"scene", "target_id": ..., "desired_state": {...}}
    — the caller applies this the same way any other desired-state push works
    (through the existing shadow-reconciliation path), Alexa is just another client.
    """
    header = directive["header"]
    namespace, name = header["namespace"], header["name"]

    if namespace == "Alexa.PowerController":
        endpoint_id = directive["endpoint"]["endpointId"]
        return {
            "target_type": "device",
            "target_id": endpoint_id,
            "desired_state": {"power": "on" if name == "TurnOn" else "off"},
        }

    if namespace == "Alexa.SceneController":
        return {
            "target_type": "scene",
            "target_id": directive["endpoint"]["endpointId"],
            "desired_state": {},
        }

    raise ValueError(f"unsupported directive: {namespace}.{name}")
