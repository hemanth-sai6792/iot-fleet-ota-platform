const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const WS_URL = import.meta.env.VITE_WS_URL ?? "ws://localhost:8000";

async function request(path: string, options?: RequestInit) {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ? JSON.stringify(body.detail) : `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const listSites = () => request("/sites");
export const createSite = (body: { name: string; type: string }) =>
  request("/sites", { method: "POST", body: JSON.stringify(body) });

export const listRooms = (site_id: string) => request(`/rooms?site_id=${site_id}`);
export const createRoom = (body: { site_id: string; name: string }) =>
  request("/rooms", { method: "POST", body: JSON.stringify(body) });

export const listDevices = (params: Record<string, string>) =>
  request(`/devices?${new URLSearchParams(params)}`);
export const createDevice = (body: Record<string, unknown>) =>
  request("/devices", { method: "POST", body: JSON.stringify(body) });
export const setDeviceDesiredState = (id: string, patch: Record<string, unknown>) =>
  request(`/devices/${id}/desired-state`, { method: "PATCH", body: JSON.stringify({ patch }) });

export const listScenes = (site_id: string) => request(`/scenes?site_id=${site_id}`);
export const createScene = (body: { site_id: string; name: string; devices: { device_id: string; target_state: Record<string, unknown> }[] }) =>
  request("/scenes", { method: "POST", body: JSON.stringify(body) });
export const activateScene = (id: string) => request(`/scenes/${id}/activate`, { method: "POST" });

export const listDivisions = (site_id: string) => request(`/divisions?site_id=${site_id}`);
export const listUnits = (division_id: string) => request(`/units?division_id=${division_id}`);

export const unitPower = (id: string, body: { desired_power: "on" | "off"; force?: boolean; reason?: string; cross_site?: boolean }): Promise<import("./types").PowerResponse> =>
  request(`/units/${id}/power`, { method: "POST", body: JSON.stringify(body) });
export const divisionPower = (id: string, body: { desired_power: "on" | "off"; force?: boolean; reason?: string; cross_site?: boolean }): Promise<import("./types").PowerResponse> =>
  request(`/divisions/${id}/power`, { method: "POST", body: JSON.stringify(body) });

export const unitUsage = (id: string) => request(`/units/${id}/usage`);
export const divisionUsage = (id: string) => request(`/divisions/${id}/usage`);
export const divisionReconciliations = (id: string) => request(`/divisions/${id}/reconciliations`);
export const listAlerts = () => request(`/alerts`);
export const listFaults = () => request(`/faults`);
export const listAudit = (site_id: string) => request(`/audit?site_id=${site_id}`);

export function connectLiveSocket(onMessage: (data: any) => void) {
  const ws = new WebSocket(`${WS_URL}/ws/live`);
  ws.onmessage = (event) => onMessage(JSON.parse(event.data));
  return ws;
}
