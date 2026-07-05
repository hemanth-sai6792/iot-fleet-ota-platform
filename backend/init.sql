CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT 'generic-sensor',
    status TEXT NOT NULL DEFAULT 'offline',
    firmware_version TEXT NOT NULL DEFAULT '1.0.0',
    desired_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    reported_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_seen TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Telemetry is partitioned by day. Naive row-per-reading on one big table
-- falls over past a few hundred million rows; range partitioning on ts keeps
-- each partition (and its indexes) small enough that recent-data queries and
-- retention (DROP TABLE on old partitions, no VACUUM storm) both stay cheap.
CREATE TABLE telemetry (
    id BIGSERIAL,
    device_id UUID NOT NULL REFERENCES devices(id),
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload JSONB NOT NULL,
    PRIMARY KEY (id, ts)
) PARTITION BY RANGE (ts);

-- Helper the core-engine calls on startup/daily to keep today+tomorrow's
-- partitions present. In production this would be a pg_partman job instead
-- of app-owned DDL.
CREATE OR REPLACE FUNCTION ensure_telemetry_partition(for_date DATE)
RETURNS void AS $$
DECLARE
    partition_name TEXT := 'telemetry_' || to_char(for_date, 'YYYY_MM_DD');
    start_ts TIMESTAMPTZ := for_date::timestamptz;
    end_ts TIMESTAMPTZ := (for_date + 1)::timestamptz;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = partition_name) THEN
        EXECUTE format(
            'CREATE TABLE %I PARTITION OF telemetry FOR VALUES FROM (%L) TO (%L)',
            partition_name, start_ts, end_ts
        );
    END IF;
END;
$$ LANGUAGE plpgsql;

SELECT ensure_telemetry_partition(CURRENT_DATE - 1);
SELECT ensure_telemetry_partition(CURRENT_DATE);
SELECT ensure_telemetry_partition(CURRENT_DATE + 1);

CREATE INDEX idx_telemetry_device_ts ON telemetry (device_id, ts DESC);

CREATE TABLE rollouts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firmware_version TEXT NOT NULL,
    previous_firmware_version TEXT NOT NULL,
    canary_percent INT NOT NULL,
    failure_threshold_percent NUMERIC NOT NULL DEFAULT 20,
    status TEXT NOT NULL DEFAULT 'running', -- running | completed | rolled_back | rolled_back_manual
    target_device_ids UUID[] NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ
);

CREATE TABLE rollout_events (
    id BIGSERIAL PRIMARY KEY,
    rollout_id UUID NOT NULL REFERENCES rollouts(id),
    device_id UUID NOT NULL REFERENCES devices(id),
    status TEXT NOT NULL, -- pending | applied | failed
    ts TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_rollout_events_rollout ON rollout_events (rollout_id);
-- one outcome per device per rollout keeps failure-rate math simple (no
-- double-counting a device that reports "failed" twice before rollback)
ALTER TABLE rollout_events ADD CONSTRAINT uq_rollout_device UNIQUE (rollout_id, device_id);
