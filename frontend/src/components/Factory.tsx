import { useEffect, useState } from "react";
import * as api from "../api/client";
import type { AuditLogEntry, BlockedDevice, Device, Division, FaultLog, LiveSnapshot, Site, ThresholdAlert, Unit } from "../api/types";
import { Sparkline } from "./Sparkline";

export function Factory({ site, live }: { site: Site; live: LiveSnapshot | null }) {
  const [divisions, setDivisions] = useState<Division[]>([]);
  const [units, setUnits] = useState<Record<string, Unit[]>>({});
  const [devices, setDevices] = useState<Record<string, Device[]>>({});
  const [usage, setUsage] = useState<Record<string, number[]>>({});
  const [reconciliations, setReconciliations] = useState<Record<string, { discrepancy_pct: number; flagged: boolean }[]>>({});
  const [faults, setFaults] = useState<FaultLog[]>([]);
  const [audit, setAudit] = useState<AuditLogEntry[]>([]);
  const [pending, setPending] = useState<{ scope: "unit" | "division"; id: string; blocked: BlockedDevice[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    const divs: Division[] = await api.listDivisions(site.id);
    setDivisions(divs);
    const unitsByDivision: Record<string, Unit[]> = {};
    const devicesByUnit: Record<string, Device[]> = {};
    const usageByScope: Record<string, number[]> = {};
    const reconByDivision: Record<string, any[]> = {};
    for (const div of divs) {
      const divUnits: Unit[] = await api.listUnits(div.id);
      unitsByDivision[div.id] = divUnits;
      usageByScope[div.id] = (await api.divisionUsage(div.id)).map((r: any) => r.kwh);
      reconByDivision[div.id] = await api.divisionReconciliations(div.id);
      for (const unit of divUnits) {
        devicesByUnit[unit.id] = await api.listDevices({ unit_id: unit.id });
        usageByScope[unit.id] = (await api.unitUsage(unit.id)).map((r: any) => r.kwh);
      }
    }
    setUnits(unitsByDivision);
    setDevices(devicesByUnit);
    setUsage(usageByScope);
    setReconciliations(reconByDivision);
    setFaults(await api.listFaults());
    setAudit(await api.listAudit(site.id));
  }

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 8000);
    return () => clearInterval(interval);
  }, [site.id]);

  const liveStatus = new Map((live?.devices ?? []).map((d) => [d.id, d.status]));

  async function commandScope(scope: "unit" | "division", id: string, desired: "on" | "off", force = false) {
    setError(null);
    try {
      const fn = scope === "unit" ? api.unitPower : api.divisionPower;
      const result = await fn(id, { desired_power: desired, force });
      if (result.blocked.length > 0 && !force) {
        setPending({ scope, id, blocked: result.blocked });
      } else {
        setPending(null);
        await refresh();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "command failed");
    }
  }

  return (
    <div>
      {error && <p className="error">{error}</p>}

      {pending && (
        <div className="modal-overlay">
          <div className="modal">
            <h3>Some devices are still completing a task</h3>
            <ul>
              {pending.blocked.map((b) => <li key={b.device_id}>{b.message}</li>)}
            </ul>
            <div className="modal-actions">
              <button onClick={() => setPending(null)}>Wait</button>
              <button className="rollback-btn" onClick={() => commandScope(pending.scope, pending.id, "off", true)}>
                Force stop anyway
              </button>
            </div>
          </div>
        </div>
      )}

      {divisions.map((division) => (
        <section key={division.id} className="panel">
          <div className="division-header">
            <h2>{division.name}</h2>
            <div>
              <button onClick={() => commandScope("division", division.id, "on")}>Power on division</button>
              <button className="rollback-btn" onClick={() => commandScope("division", division.id, "off")}>Power off division</button>
            </div>
          </div>
          <p className="ts">Threshold: {division.alert_threshold_kw ?? "none"} kW</p>
          <Sparkline values={usage[division.id] ?? []} />
          {reconciliations[division.id]?.[0] && (
            <p className={reconciliations[division.id][0].flagged ? "error" : "ts"}>
              Meter reconciliation: {Number(reconciliations[division.id][0].discrepancy_pct).toFixed(1)}% discrepancy
              {reconciliations[division.id][0].flagged ? " — flagged" : ""}
            </p>
          )}

          {(units[division.id] ?? []).map((unit) => (
            <div key={unit.id} className="unit-block">
              <div className="division-header">
                <h3>{unit.name}</h3>
                <div>
                  <button onClick={() => commandScope("unit", unit.id, "on")}>On</button>
                  <button className="rollback-btn" onClick={() => commandScope("unit", unit.id, "off")}>Off</button>
                </div>
              </div>
              <Sparkline values={usage[unit.id] ?? []} />
              <table>
                <tbody>
                  {(devices[unit.id] ?? []).map((device) => (
                    <tr key={device.id}>
                      <td>{device.name}</td>
                      <td>
                        <span className={`badge badge-${liveStatus.get(device.id) ?? device.status}`}>
                          {liveStatus.get(device.id) ?? device.status}
                        </span>
                      </td>
                      <td>
                        <button
                          onClick={() =>
                            api.setDeviceDesiredState(device.id, {
                              power: device.desired_state.power === "on" ? "off" : "on",
                            })
                          }
                        >
                          {device.desired_state.power === "on" ? "turn off" : "turn on"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </section>
      ))}

      <section className="panel">
        <h2>Fault log</h2>
        {faults.length === 0 && <p className="empty">no faults recorded</p>}
        <ul>
          {faults.map((f) => <li key={f.id}>[{new Date(f.ts).toLocaleTimeString()}] {f.code}: {f.message}</li>)}
        </ul>
      </section>

      <section className="panel">
        <h2>Audit trail</h2>
        {audit.length === 0 && <p className="empty">no remote actions logged yet</p>}
        <ul>
          {audit.map((a) => (
            <li key={a.id}>
              [{new Date(a.ts).toLocaleTimeString()}] {a.actor}: {a.action} on {a.target_type}
              {a.reason ? ` — "${a.reason}"` : ""}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
