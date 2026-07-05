import type { Device } from "../api/types";

function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

export function FleetList({
  devices,
}: {
  devices: Pick<Device, "id" | "name" | "status" | "firmware_version" | "last_seen">[];
}) {
  return (
    <section className="panel">
      <h2>Fleet ({devices.length} devices)</h2>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Status</th>
            <th>Firmware</th>
            <th>Last seen</th>
          </tr>
        </thead>
        <tbody>
          {devices.map((d) => (
            <tr key={d.id}>
              <td>{d.name}</td>
              <td>
                <span className={`badge badge-${d.status}`}>{d.status}</span>
              </td>
              <td>{d.firmware_version}</td>
              <td>{timeAgo(d.last_seen)}</td>
            </tr>
          ))}
          {devices.length === 0 && (
            <tr>
              <td colSpan={4} className="empty">
                No devices registered yet — waiting for the simulator to connect.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}
