from decimal import Decimal

from app.factory import check_threshold_breach, plan_cascade_command, reconcile_meter, sum_unit_usage


def _device(id_, status, name="device", unit_name="Assembly Line 1", division_name="Assembly Wing"):
    return {"id": id_, "name": name, "status": status, "unit_name": unit_name, "division_name": division_name}


def test_cascade_commands_idle_devices():
    devices = [_device("1", "online"), _device("2", "offline")]
    plan = plan_cascade_command(devices)
    assert plan.to_command == ["1", "2"]
    assert plan.blocked == []
    assert plan.is_clear


def test_cascade_blocks_busy_device_without_force():
    devices = [
        _device("1", "online"),
        _device("2", "running_task", name="Robotic welder"),
    ]
    plan = plan_cascade_command(devices)
    assert plan.to_command == ["1"]
    assert len(plan.blocked) == 1
    assert not plan.is_clear
    assert "Robotic welder" in plan.blocked[0].message
    assert "Assembly Line 1" in plan.blocked[0].message
    assert "Assembly Wing" in plan.blocked[0].message


def test_cascade_force_includes_busy_devices():
    devices = [_device("1", "running_task")]
    plan = plan_cascade_command(devices, force=True)
    assert plan.to_command == ["1"]
    assert plan.blocked == []


def test_sum_unit_usage():
    assert sum_unit_usage([Decimal("10.5"), Decimal("4.5")]) == Decimal("15.0")
    assert sum_unit_usage([]) == Decimal("0")


def test_reconcile_meter_within_tolerance():
    result = reconcile_meter(Decimal("100"), Decimal("98"), Decimal("5"))
    assert result["flagged"] is False


def test_reconcile_meter_beyond_tolerance():
    result = reconcile_meter(Decimal("100"), Decimal("80"), Decimal("5"))
    assert result["flagged"] is True
    assert result["discrepancy_pct"] == Decimal("20")


def test_reconcile_meter_zero_division_reading():
    result = reconcile_meter(Decimal("0"), Decimal("5"), Decimal("5"))
    assert result["flagged"] is True


def test_threshold_breach():
    assert check_threshold_breach(Decimal("55"), Decimal("50")) is True
    assert check_threshold_breach(Decimal("40"), Decimal("50")) is False
