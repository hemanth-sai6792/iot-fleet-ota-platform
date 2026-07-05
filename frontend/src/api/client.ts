const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const WS_URL = import.meta.env.VITE_WS_URL ?? "ws://localhost:8000";

export async function fetchDevices() {
  const res = await fetch(`${API_URL}/devices`);
  if (!res.ok) throw new Error("failed to fetch devices");
  return res.json();
}

export async function fetchRollouts() {
  const res = await fetch(`${API_URL}/rollouts`);
  if (!res.ok) throw new Error("failed to fetch rollouts");
  return res.json();
}

export async function startRollout(body: {
  firmware_version: string;
  canary_percent: number;
  failure_threshold_percent: number;
}) {
  const res = await fetch(`${API_URL}/rollouts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json()).detail ?? "failed to start rollout");
  return res.json();
}

export async function rollbackRollout(id: string) {
  const res = await fetch(`${API_URL}/rollouts/${id}/rollback`, { method: "POST" });
  if (!res.ok) throw new Error("failed to roll back");
  return res.json();
}

export function connectFleetSocket(onMessage: (data: any) => void) {
  const ws = new WebSocket(`${WS_URL}/ws/fleet`);
  ws.onmessage = (event) => onMessage(JSON.parse(event.data));
  return ws;
}
