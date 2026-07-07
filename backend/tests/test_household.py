from datetime import datetime

from app.household import (
    evaluate_rule,
    evaluate_sensor_trigger,
    evaluate_time_trigger,
    evaluate_voice_trigger,
    validate_alexa_name,
)


def test_valid_room_name_passes():
    assert validate_alexa_name("Living Room") == []


def test_empty_name_rejected():
    assert validate_alexa_name("   ") != []


def test_purely_numeric_name_rejected():
    errors = validate_alexa_name("123")
    assert any("numeric" in e for e in errors)


def test_reserved_word_rejected():
    errors = validate_alexa_name("Alexa Room")
    assert any("reserved" in e for e in errors)


def test_special_characters_rejected():
    errors = validate_alexa_name("Kitchen!!!")
    assert any("letters, numbers" in e for e in errors)


def test_apostrophe_and_hyphen_allowed():
    assert validate_alexa_name("Kid's Room") == []
    assert validate_alexa_name("Walk-in Closet") == []


def test_time_trigger_matches_exact_minute():
    config = {"at": "07:30"}
    assert evaluate_time_trigger(config, datetime(2026, 1, 1, 7, 30)) is True
    assert evaluate_time_trigger(config, datetime(2026, 1, 1, 7, 31)) is False


def test_time_trigger_respects_day_filter():
    config = {"at": "07:30", "days": ["mon", "wed", "fri"]}
    monday = datetime(2026, 1, 5, 7, 30)  # a Monday
    tuesday = datetime(2026, 1, 6, 7, 30)  # a Tuesday
    assert evaluate_time_trigger(config, monday) is True
    assert evaluate_time_trigger(config, tuesday) is False


def test_sensor_trigger_eq():
    config = {"field": "motion", "op": "eq", "value": True}
    assert evaluate_sensor_trigger(config, {"motion": True}) is True
    assert evaluate_sensor_trigger(config, {"motion": False}) is False


def test_sensor_trigger_missing_field_is_false():
    config = {"field": "motion", "op": "eq", "value": True}
    assert evaluate_sensor_trigger(config, {}) is False


def test_sensor_trigger_gt():
    config = {"field": "temperature_c", "op": "gt", "value": 25}
    assert evaluate_sensor_trigger(config, {"temperature_c": 30}) is True
    assert evaluate_sensor_trigger(config, {"temperature_c": 20}) is False


def test_voice_trigger_matches_case_insensitive():
    config = {"phrase": "Good Night"}
    assert evaluate_voice_trigger(config, "good night") is True
    assert evaluate_voice_trigger(config, "good morning") is False


def test_evaluate_rule_dispatches_by_trigger_type():
    rule = {"trigger_type": "voice", "trigger_config": {"phrase": "movie time"}}
    assert evaluate_rule(rule, spoken_phrase="Movie Time") is True
    assert evaluate_rule(rule, spoken_phrase="bedtime") is False
