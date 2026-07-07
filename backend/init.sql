CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- A site is one customer install: a household, a showroom, or a factory.
-- Household/showroom sites use rooms+scenes; factory sites use
-- divisions+units. A device belongs to exactly one of those, never both.
CREATE TABLE sites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('household', 'showroom', 'factory')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ===== Household / showroom =====

CREATE TABLE rooms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id UUID NOT NULL REFERENCES sites(id),
    name TEXT NOT NULL,
    UNIQUE (site_id, name)
);

CREATE TABLE scenes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id UUID NOT NULL REFERENCES sites(id),
    name TEXT NOT NULL,
    alexa_scene_id TEXT,
    UNIQUE (site_id, name)
);

CREATE TABLE rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id UUID NOT NULL REFERENCES sites(id),
    name TEXT NOT NULL,
    trigger_type TEXT NOT NULL CHECK (trigger_type IN ('time', 'sensor', 'voice')),
    trigger_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    action_type TEXT NOT NULL CHECK (action_type IN ('device', 'scene')),
    action_target_id UUID NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true
);

-- ===== Factory =====

CREATE TABLE divisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id UUID NOT NULL REFERENCES sites(id),
    name TEXT NOT NULL,
    -- divisions are Controllable too: a master switch that cascades to
    -- every unit (and every device) beneath them.
    desired_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    reported_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    alert_threshold_kw NUMERIC,
    UNIQUE (site_id, name)
);

CREATE TABLE units (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    division_id UUID NOT NULL REFERENCES divisions(id),
    name TEXT NOT NULL,
    desired_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    reported_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    alert_threshold_kw NUMERIC,
    UNIQUE (division_id, name)
);

-- ===== Devices (shared core) =====

CREATE TABLE devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id UUID NOT NULL REFERENCES sites(id),
    name TEXT NOT NULL,
    device_type TEXT NOT NULL,
    room_id UUID REFERENCES rooms(id),
    unit_id UUID REFERENCES units(id),
    -- running_task = mid-operation and not safely interruptible right now
    -- (mid-weld, mid-press-stroke). Cascading shutdowns must not force
    -- these off silently — see the interlock in app/factory.py.
    status TEXT NOT NULL DEFAULT 'offline'
        CHECK (status IN ('online', 'offline', 'fault', 'running_task')),
    task_interruptible BOOLEAN NOT NULL DEFAULT true,
    desired_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    reported_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_seen TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (num_nonnulls(room_id, unit_id) <= 1)
);

CREATE TABLE scene_devices (
    scene_id UUID NOT NULL REFERENCES scenes(id),
    device_id UUID NOT NULL REFERENCES devices(id),
    target_state JSONB NOT NULL,
    PRIMARY KEY (scene_id, device_id)
);

CREATE INDEX idx_devices_room ON devices (room_id);
CREATE INDEX idx_devices_unit ON devices (unit_id);
CREATE INDEX idx_units_division ON units (division_id);

-- ===== Factory usage / maintenance =====

-- Metered at unit + division granularity only — individually metering
-- every device is cost-prohibitive at factory scale, and capping the
-- ingestion cardinality here is also what keeps this "simple but strong"
-- at large scale. Same day-partitioning pattern as any high-volume
-- telemetry table.
CREATE TABLE usage_readings (
    id BIGSERIAL,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('unit', 'division')),
    scope_id UUID NOT NULL,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    kwh NUMERIC NOT NULL,
    PRIMARY KEY (id, ts)
) PARTITION BY RANGE (ts);

CREATE OR REPLACE FUNCTION ensure_usage_partition(for_date DATE)
RETURNS void AS $$
DECLARE
    partition_name TEXT := 'usage_readings_' || to_char(for_date, 'YYYY_MM_DD');
    start_ts TIMESTAMPTZ := for_date::timestamptz;
    end_ts TIMESTAMPTZ := (for_date + 1)::timestamptz;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = partition_name) THEN
        EXECUTE format(
            'CREATE TABLE %I PARTITION OF usage_readings FOR VALUES FROM (%L) TO (%L)',
            partition_name, start_ts, end_ts
        );
    END IF;
END;
$$ LANGUAGE plpgsql;

SELECT ensure_usage_partition(CURRENT_DATE - 1);
SELECT ensure_usage_partition(CURRENT_DATE);
SELECT ensure_usage_partition(CURRENT_DATE + 1);

CREATE INDEX idx_usage_scope_ts ON usage_readings (scope_type, scope_id, ts DESC);

-- A device fault/error is control-plane state, tracked per device
-- regardless of the fact that only units/divisions are metered.
CREATE TABLE fault_logs (
    id BIGSERIAL PRIMARY KEY,
    device_id UUID NOT NULL REFERENCES devices(id),
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE threshold_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope_type TEXT NOT NULL CHECK (scope_type IN ('unit', 'division')),
    scope_id UUID NOT NULL,
    threshold_kw NUMERIC NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'resolved')),
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

-- Compares a division's own main-meter reading against the sum of its
-- units' sub-meters. A persistent mismatch beyond tolerance usually means
-- sensor drift or a wiring fault, not an actual usage anomaly.
CREATE TABLE meter_reconciliations (
    id BIGSERIAL PRIMARY KEY,
    division_id UUID NOT NULL REFERENCES divisions(id),
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    division_reading_kwh NUMERIC NOT NULL,
    units_sum_kwh NUMERIC NOT NULL,
    discrepancy_pct NUMERIC NOT NULL,
    flagged BOOLEAN NOT NULL DEFAULT false
);

-- Every remote/company-side action gets logged. `reason` is mandatory at
-- the application layer for cross-site troubleshooting access — this
-- table doesn't enforce that itself (household users acting on their own
-- site don't need a reason), the API layer does.
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    actor TEXT NOT NULL,
    site_id UUID NOT NULL REFERENCES sites(id),
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id UUID NOT NULL,
    reason TEXT,
    ts TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_site_ts ON audit_log (site_id, ts DESC);
