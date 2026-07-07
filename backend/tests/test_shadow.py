from app.shadow import compute_delta


def test_no_drift_returns_empty_delta():
    desired = {"power": "on"}
    reported = {"power": "on"}
    assert compute_delta(desired, reported) == {}


def test_drift_returns_only_mismatched_keys():
    desired = {"power": "off", "brightness": 80}
    reported = {"power": "on", "brightness": 80}
    assert compute_delta(desired, reported) == {"power": "off"}


def test_missing_reported_key_counts_as_drift():
    desired = {"power": "on"}
    reported = {}
    assert compute_delta(desired, reported) == {"power": "on"}


def test_extra_reported_keys_are_ignored():
    desired = {"power": "on"}
    reported = {"power": "on", "temperature_c": 21.5}
    assert compute_delta(desired, reported) == {}
