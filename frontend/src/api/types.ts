export interface Site {
  id: string;
  name: string;
  type: "household" | "showroom" | "factory";
}

export interface Room {
  id: string;
  site_id: string;
  name: string;
}

export interface Device {
  id: string;
  site_id: string;
  name: string;
  device_type: string;
  room_id: string | null;
  unit_id: string | null;
  status: "online" | "offline" | "fault" | "running_task";
  task_interruptible: boolean;
  desired_state: Record<string, unknown>;
  reported_state: Record<string, unknown>;
  last_seen: string | null;
}

export interface Scene {
  id: string;
  site_id: string;
  name: string;
  alexa_scene_id: string | null;
}

export interface Rule {
  id: string;
  site_id: string;
  name: string;
  trigger_type: "time" | "sensor" | "voice";
  trigger_config: Record<string, unknown>;
  action_type: "device" | "scene";
  action_target_id: string;
  enabled: boolean;
}

export interface Division {
  id: string;
  site_id: string;
  name: string;
  desired_state: Record<string, unknown>;
  reported_state: Record<string, unknown>;
  alert_threshold_kw: number | null;
}

export interface Unit {
  id: string;
  division_id: string;
  name: string;
  desired_state: Record<string, unknown>;
  reported_state: Record<string, unknown>;
  alert_threshold_kw: number | null;
}

export interface BlockedDevice {
  device_id: string;
  device_name: string;
  unit_name: string;
  division_name: string;
  message: string;
}

export interface PowerResponse {
  commanded_device_ids: string[];
  blocked: BlockedDevice[];
}

export interface ThresholdAlert {
  id: string;
  scope_type: "unit" | "division";
  scope_id: string;
  threshold_kw: number;
  status: "active" | "resolved";
  triggered_at: string;
}

export interface FaultLog {
  id: number;
  device_id: string;
  code: string;
  message: string;
  ts: string;
}

export interface AuditLogEntry {
  id: number;
  actor: string;
  action: string;
  target_type: string;
  target_id: string;
  reason: string | null;
  ts: string;
}

export interface UsageReading {
  ts: string;
  kwh: number;
}

export interface LiveSnapshot {
  type: "live_snapshot";
  devices: Pick<Device, "id" | "site_id" | "name" | "status" | "room_id" | "unit_id" | "last_seen">[];
  units: Pick<Unit, "id" | "division_id" | "name" | "desired_state">[];
  divisions: Pick<Division, "id" | "site_id" | "name" | "desired_state">[];
  active_alerts: Pick<ThresholdAlert, "id" | "scope_type" | "scope_id" | "threshold_kw">[];
}
