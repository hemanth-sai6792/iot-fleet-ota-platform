import os

POSTGRES_DSN = os.environ.get(
    "POSTGRES_DSN", "postgresql://iot:iot@localhost:5432/home_automation"
)
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))

# Devices are the only physical MQTT clients. Units and divisions are
# logical groupings (a cascade shutdown fans out to the devices inside
# them) except for their meters, which do publish real readings.
TOPIC_DEVICE_REPORTED = "devices/{device_id}/state/reported"
TOPIC_DEVICE_DESIRED = "devices/{device_id}/state/desired"
TOPIC_DEVICE_HEARTBEAT = "devices/{device_id}/heartbeat"
TOPIC_DEVICE_REPORTED_WILDCARD = "devices/+/state/reported"
TOPIC_DEVICE_HEARTBEAT_WILDCARD = "devices/+/heartbeat"

TOPIC_UNIT_USAGE_WILDCARD = "units/+/usage"
TOPIC_DIVISION_USAGE_WILDCARD = "divisions/+/usage"

# how stale a device's last heartbeat can be before it's considered offline
OFFLINE_AFTER_SECONDS = 30
# how often the shadow-reconciliation loop re-checks drift for devices that
# didn't just receive a message (catches desired-state changes made via the API)
RECONCILE_INTERVAL_SECONDS = 5
# how often the usage-analysis loop checks for threshold breaches and runs
# meter reconciliation
USAGE_MONITOR_INTERVAL_SECONDS = 10
# tolerance before a division-vs-units meter mismatch gets flagged as a
# likely sensor fault rather than real usage
METER_RECONCILE_TOLERANCE_PCT = 5
