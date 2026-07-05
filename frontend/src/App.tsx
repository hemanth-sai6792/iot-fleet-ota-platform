import { useEffect, useState } from "react";
import { connectFleetSocket, fetchDevices, fetchRollouts } from "./api/client";
import { FleetList } from "./components/FleetList";
import { RolloutPanel } from "./components/RolloutPanel";
import type { FleetSnapshot } from "./api/types";

export default function App() {
  const [snapshot, setSnapshot] = useState<FleetSnapshot>({
    type: "fleet_snapshot",
    devices: [],
    rollouts: [],
  });
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    // seed initial state over REST so the dashboard isn't empty while the
    // websocket connects, then let the socket take over for live updates
    fetchDevices().then((devices) =>
      setSnapshot((s) => ({ ...s, devices }))
    );
    fetchRollouts().then((rollouts) =>
      setSnapshot((s) => ({
        ...s,
        rollouts: rollouts.map((r: any) => ({ ...r, applied: 0, failed: 0 })),
      }))
    );

    const ws = connectFleetSocket((data) => {
      if (data.type === "fleet_snapshot") setSnapshot(data);
    });
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    return () => ws.close();
  }, []);

  return (
    <div className="app">
      <header>
        <h1>IoT Device Fleet & OTA Management</h1>
        <span className={`badge ${connected ? "badge-online" : "badge-offline"}`}>
          {connected ? "live" : "connecting..."}
        </span>
      </header>
      <main>
        <FleetList devices={snapshot.devices} />
        <RolloutPanel rollouts={snapshot.rollouts} />
      </main>
    </div>
  );
}
