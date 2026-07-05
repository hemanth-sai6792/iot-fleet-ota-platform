export interface Device {
  id: string;
  name: string;
  model: string;
  status: "online" | "offline";
  firmware_version: string;
  desired_state: Record<string, unknown>;
  reported_state: Record<string, unknown>;
  last_seen: string | null;
  created_at: string;
}

export interface Rollout {
  id: string;
  firmware_version: string;
  previous_firmware_version: string;
  canary_percent: number;
  failure_threshold_percent: number;
  status: "running" | "completed" | "rolled_back" | "rolled_back_manual";
  target_device_ids: string[];
  started_at: string;
  ended_at: string | null;
}

export interface FleetSnapshot {
  type: "fleet_snapshot";
  devices: Pick<Device, "id" | "name" | "status" | "firmware_version" | "last_seen">[];
  rollouts: (Pick<Rollout, "id" | "firmware_version" | "status" | "target_device_ids"> & {
    applied: number;
    failed: number;
  })[];
}
