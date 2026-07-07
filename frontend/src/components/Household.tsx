import { useEffect, useState } from "react";
import * as api from "../api/client";
import type { Device, LiveSnapshot, Room, Scene, Site } from "../api/types";

const DEVICE_TYPES = ["switch", "dimmer", "thermostat", "lock"];

export function Household({ site, live }: { site: Site; live: LiveSnapshot | null }) {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [newRoomName, setNewRoomName] = useState("");
  const [newDevice, setNewDevice] = useState({ name: "", device_type: DEVICE_TYPES[0], room_id: "" });
  const [newSceneName, setNewSceneName] = useState("");
  const [sceneTargets, setSceneTargets] = useState<Record<string, "on" | "off" | undefined>>({});
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    const [r, d, s] = await Promise.all([
      api.listRooms(site.id),
      api.listDevices({ site_id: site.id }),
      api.listScenes(site.id),
    ]);
    setRooms(r);
    setDevices(d);
    setScenes(s);
  }

  useEffect(() => {
    refresh();
  }, [site.id]);

  const liveStatus = new Map((live?.devices ?? []).map((d) => [d.id, d.status]));

  async function handleAddRoom(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createRoom({ site_id: site.id, name: newRoomName });
      setNewRoomName("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed to add room");
    }
  }

  async function handleAddDevice(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createDevice({
        site_id: site.id, name: newDevice.name, device_type: newDevice.device_type,
        room_id: newDevice.room_id || null,
      });
      setNewDevice({ name: "", device_type: DEVICE_TYPES[0], room_id: "" });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed to add device");
    }
  }

  async function togglePower(device: Device) {
    const current = (device.desired_state.power as string) ?? "off";
    await api.setDeviceDesiredState(device.id, { power: current === "on" ? "off" : "on" });
  }

  async function handleCreateScene(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const sceneDevices = Object.entries(sceneTargets)
      .filter(([, power]) => power)
      .map(([device_id, power]) => ({ device_id, target_state: { power } }));
    try {
      await api.createScene({ site_id: site.id, name: newSceneName, devices: sceneDevices });
      setNewSceneName("");
      setSceneTargets({});
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed to create scene");
    }
  }

  return (
    <div>
      {error && <p className="error">{error}</p>}

      <section className="panel">
        <h2>Rooms</h2>
        {rooms.map((room) => (
          <div key={room.id} className="room-block">
            <h3>{room.name}</h3>
            <table>
              <tbody>
                {devices.filter((d) => d.room_id === room.id).map((device) => (
                  <tr key={device.id}>
                    <td>{device.name}</td>
                    <td>{device.device_type}</td>
                    <td>
                      <span className={`badge badge-${liveStatus.get(device.id) ?? device.status}`}>
                        {liveStatus.get(device.id) ?? device.status}
                      </span>
                    </td>
                    <td>
                      <button onClick={() => togglePower(device)}>
                        {(device.desired_state.power as string) === "on" ? "turn off" : "turn on"}
                      </button>
                    </td>
                  </tr>
                ))}
                {devices.filter((d) => d.room_id === room.id).length === 0 && (
                  <tr><td colSpan={4} className="empty">no devices in this room yet</td></tr>
                )}
              </tbody>
            </table>
          </div>
        ))}
        <form className="inline-form" onSubmit={handleAddRoom}>
          <input placeholder="New room name" value={newRoomName} onChange={(e) => setNewRoomName(e.target.value)} />
          <button type="submit">Add room</button>
        </form>
      </section>

      <section className="panel">
        <h2>Add a device</h2>
        <form className="inline-form" onSubmit={handleAddDevice}>
          <input placeholder="Device name" value={newDevice.name} onChange={(e) => setNewDevice({ ...newDevice, name: e.target.value })} />
          <select value={newDevice.device_type} onChange={(e) => setNewDevice({ ...newDevice, device_type: e.target.value })}>
            {DEVICE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <select value={newDevice.room_id} onChange={(e) => setNewDevice({ ...newDevice, room_id: e.target.value })}>
            <option value="">Unassigned</option>
            {rooms.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
          <button type="submit">Add device</button>
        </form>
      </section>

      <section className="panel">
        <h2>Scenes</h2>
        {scenes.map((scene) => (
          <div key={scene.id} className="scene-row">
            <strong>{scene.name}</strong>
            <button onClick={() => api.activateScene(scene.id)}>Activate</button>
          </div>
        ))}
        {scenes.length === 0 && <p className="empty">no scenes yet</p>}

        <form className="scene-form" onSubmit={handleCreateScene}>
          <input placeholder="Scene name (e.g. Movie night)" value={newSceneName} onChange={(e) => setNewSceneName(e.target.value)} />
          {devices.map((device) => (
            <label key={device.id} className="scene-device-row">
              {device.name}
              <select
                value={sceneTargets[device.id] ?? ""}
                onChange={(e) => setSceneTargets({ ...sceneTargets, [device.id]: (e.target.value || undefined) as "on" | "off" | undefined })}
              >
                <option value="">skip</option>
                <option value="on">turn on</option>
                <option value="off">turn off</option>
              </select>
            </label>
          ))}
          <button type="submit">Create scene</button>
        </form>
      </section>
    </div>
  );
}
