"""Household/showroom domain logic: rooms, scenes, and rule triggers.

Pure functions only — no database, no MQTT, no Alexa SDK calls — so the
actual decision logic (is this name voice-safe? does this rule fire?) is
unit-testable without any of that infrastructure running.
"""

import re
from datetime import datetime
from typing import Any

# Alexa disallows names that collide with its own wake words / invocation
# terms — a room or scene named "Alexa" or "Echo" would make voice control
# of it ambiguous or impossible. This isn't a real Amazon reserved-word
# list, just the honest subset that actually matters for this project.
ALEXA_RESERVED_WORDS = {"alexa", "echo", "amazon", "computer"}

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 '\-]{0,99}$")


def validate_alexa_name(name: str) -> list[str]:
    """Validate a room/scene name against Alexa voice-discovery constraints.

    Returns a list of human-readable errors; empty list means the name is
    safe to save. Checked here (fail fast at creation) rather than only
    discovered later when Alexa's device-discovery silently skips it.
    """
    errors = []
    stripped = name.strip() if name else ""
    if not stripped:
        return ["name cannot be empty"]
    if len(stripped) > 100:
        errors.append("name must be 100 characters or fewer")
    if not _NAME_PATTERN.match(stripped):
        errors.append(
            "name may only contain letters, numbers, spaces, apostrophes, and hyphens"
        )
    if stripped.isdigit():
        errors.append("name cannot be purely numeric — not voice-discoverable")
    words = set(stripped.lower().split())
    hit = words & ALEXA_RESERVED_WORDS
    if hit:
        errors.append(f"name cannot contain reserved word(s): {', '.join(sorted(hit))}")
    return errors


def evaluate_time_trigger(config: dict[str, Any], now: datetime) -> bool:
    at = config.get("at")
    if not at:
        return False
    try:
        hour, minute = (int(part) for part in at.split(":"))
    except ValueError:
        return False
    if now.hour != hour or now.minute != minute:
        return False
    days = config.get("days")
    if days:
        today = now.strftime("%a").lower()[:3]
        if today not in {d.lower()[:3] for d in days}:
            return False
    return True


_SENSOR_OPS = {
    "eq": lambda a, b: a == b,
    "neq": lambda a, b: a != b,
    "gt": lambda a, b: a > b,
    "lt": lambda a, b: a < b,
}


def evaluate_sensor_trigger(config: dict[str, Any], reported_state: dict[str, Any]) -> bool:
    field = config.get("field")
    if field is None or field not in reported_state:
        return False
    op = _SENSOR_OPS.get(config.get("op", "eq"))
    if op is None:
        return False
    return op(reported_state[field], config.get("value"))


def evaluate_voice_trigger(config: dict[str, Any], spoken_phrase: str) -> bool:
    phrase = config.get("phrase", "").strip().lower()
    return bool(phrase) and spoken_phrase.strip().lower() == phrase


def evaluate_rule(
    rule: dict[str, Any],
    *,
    now: datetime | None = None,
    reported_state: dict[str, Any] | None = None,
    spoken_phrase: str | None = None,
) -> bool:
    """Strategy dispatch: routes to the evaluator matching the rule's trigger_type."""
    trigger_type = rule["trigger_type"]
    config = rule["trigger_config"]
    if trigger_type == "time":
        return evaluate_time_trigger(config, now or datetime.now())
    if trigger_type == "sensor":
        return evaluate_sensor_trigger(config, reported_state or {})
    if trigger_type == "voice":
        return evaluate_voice_trigger(config, spoken_phrase or "")
    raise ValueError(f"unknown trigger_type: {trigger_type}")
