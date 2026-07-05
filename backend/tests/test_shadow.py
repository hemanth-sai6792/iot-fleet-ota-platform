from app.shadow import compute_delta


def test_no_drift_returns_empty_delta():
    desired = {"firmware_version": "1.2.0"}
    reported = {"firmware_version": "1.2.0"}
    assert compute_delta(desired, reported) == {}


def test_drift_returns_only_mismatched_keys():
    desired = {"firmware_version": "1.3.0", "sample_rate": 10}
    reported = {"firmware_version": "1.2.0", "sample_rate": 10}
    assert compute_delta(desired, reported) == {"firmware_version": "1.3.0"}


def test_missing_reported_key_counts_as_drift():
    desired = {"firmware_version": "1.3.0"}
    reported = {}
    assert compute_delta(desired, reported) == {"firmware_version": "1.3.0"}


def test_extra_reported_keys_are_ignored():
    desired = {"firmware_version": "1.2.0"}
    reported = {"firmware_version": "1.2.0", "temperature_c": 21.5}
    assert compute_delta(desired, reported) == {}
