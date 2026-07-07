import pytest

from app.alexa import build_discovery_response, handle_directive


def test_discovery_maps_known_device_type():
    devices = [{"id": "abc", "name": "Kitchen Light", "device_type": "dimmer"}]
    resp = build_discovery_response(devices)
    endpoints = resp["event"]["payload"]["endpoints"]
    assert len(endpoints) == 1
    assert endpoints[0]["friendlyName"] == "Kitchen Light"
    assert endpoints[0]["displayCategories"] == ["LIGHT"]


def test_discovery_skips_unknown_device_type():
    devices = [{"id": "abc", "name": "Mystery box", "device_type": "flux_capacitor"}]
    resp = build_discovery_response(devices)
    assert resp["event"]["payload"]["endpoints"] == []


def test_power_controller_turn_on_directive():
    directive = {
        "header": {"namespace": "Alexa.PowerController", "name": "TurnOn"},
        "endpoint": {"endpointId": "device-1"},
    }
    command = handle_directive(directive)
    assert command == {"target_type": "device", "target_id": "device-1", "desired_state": {"power": "on"}}


def test_power_controller_turn_off_directive():
    directive = {
        "header": {"namespace": "Alexa.PowerController", "name": "TurnOff"},
        "endpoint": {"endpointId": "device-1"},
    }
    command = handle_directive(directive)
    assert command["desired_state"] == {"power": "off"}


def test_unsupported_directive_raises():
    directive = {"header": {"namespace": "Alexa.Unknown", "name": "DoStuff"}, "endpoint": {"endpointId": "x"}}
    with pytest.raises(ValueError):
        handle_directive(directive)
