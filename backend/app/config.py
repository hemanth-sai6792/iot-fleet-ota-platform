import os

POSTGRES_DSN = os.environ.get(
    "POSTGRES_DSN", "postgresql://iot:iot@localhost:5432/iot_fleet"
)
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))

TOPIC_REPORTED = "devices/{device_id}/state/reported"
TOPIC_DESIRED = "devices/{device_id}/state/desired"
TOPIC_HEARTBEAT = "devices/{device_id}/heartbeat"
TOPIC_REPORTED_WILDCARD = "devices/+/state/reported"
TOPIC_HEARTBEAT_WILDCARD = "devices/+/heartbeat"

# how stale a device's last heartbeat can be before it's considered offline
OFFLINE_AFTER_SECONDS = 30
# how often the shadow-reconciliation loop re-checks drift for devices that
# didn't just receive a message (catches desired-state changes made via the API)
RECONCILE_INTERVAL_SECONDS = 5
# how often the rollout monitor re-evaluates failure rates
ROLLOUT_MONITOR_INTERVAL_SECONDS = 3
# minimum number of reporting devices before we trust a failure-rate reading
# (avoids rolling back on a single early failure in a 1% canary)
ROLLOUT_MIN_SAMPLE_SIZE = 3
