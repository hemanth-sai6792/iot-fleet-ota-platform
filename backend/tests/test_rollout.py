from app.rollout import evaluate_rollout_health, select_canary_devices


def test_select_canary_devices_respects_percent():
    devices = [str(i) for i in range(100)]
    selected = select_canary_devices(devices, 20)
    assert len(selected) == 20
    assert set(selected).issubset(set(devices))


def test_select_canary_devices_always_at_least_one():
    devices = [str(i) for i in range(10)]
    selected = select_canary_devices(devices, 1)
    assert len(selected) == 1


def test_select_canary_devices_never_exceeds_fleet_size():
    devices = [str(i) for i in range(3)]
    selected = select_canary_devices(devices, 200)
    assert len(selected) == 3


def test_select_canary_devices_empty_fleet():
    assert select_canary_devices([], 20) == []


def test_no_rollback_below_minimum_sample_size():
    # 1 failure out of 1 report is 100% failure rate, but too few samples to trust
    assert evaluate_rollout_health(applied=0, failed=1, pending=9, failure_threshold_percent=20) is False


def test_rollback_triggered_above_threshold():
    assert evaluate_rollout_health(applied=2, failed=3, pending=5, failure_threshold_percent=20) is True


def test_no_rollback_below_threshold():
    assert evaluate_rollout_health(applied=9, failed=1, pending=0, failure_threshold_percent=20) is False


def test_rollback_at_exact_threshold():
    # 2/10 = 20% failure rate, threshold is 20% -> should trigger (>=)
    assert evaluate_rollout_health(applied=8, failed=2, pending=0, failure_threshold_percent=20) is True
