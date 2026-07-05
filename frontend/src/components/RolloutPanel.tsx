import { useState } from "react";
import { rollbackRollout, startRollout } from "../api/client";
import type { FleetSnapshot } from "../api/types";

const STATUS_LABEL: Record<string, string> = {
  running: "Running",
  completed: "Completed",
  rolled_back: "Auto rolled back",
  rolled_back_manual: "Rolled back (manual)",
};

export function RolloutPanel({ rollouts }: { rollouts: FleetSnapshot["rollouts"] }) {
  const [firmwareVersion, setFirmwareVersion] = useState("1.1.0");
  const [canaryPercent, setCanaryPercent] = useState(20);
  const [failureThreshold, setFailureThreshold] = useState(20);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await startRollout({
        firmware_version: firmwareVersion,
        canary_percent: canaryPercent,
        failure_threshold_percent: failureThreshold,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed to start rollout");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="panel">
      <h2>OTA Rollouts</h2>
      <form className="rollout-form" onSubmit={handleSubmit}>
        <label>
          Firmware version
          <input value={firmwareVersion} onChange={(e) => setFirmwareVersion(e.target.value)} />
        </label>
        <label>
          Canary %
          <input
            type="number"
            min={1}
            max={100}
            value={canaryPercent}
            onChange={(e) => setCanaryPercent(Number(e.target.value))}
          />
        </label>
        <label>
          Rollback threshold %
          <input
            type="number"
            min={1}
            max={100}
            value={failureThreshold}
            onChange={(e) => setFailureThreshold(Number(e.target.value))}
          />
        </label>
        <button type="submit" disabled={submitting}>
          {submitting ? "Starting..." : "Start Rollout"}
        </button>
      </form>
      {error && <p className="error">{error}</p>}

      <div className="rollout-list">
        {rollouts.map((r) => {
          const total = r.target_device_ids.length || 1;
          const appliedPct = (r.applied / total) * 100;
          const failedPct = (r.failed / total) * 100;
          return (
            <div key={r.id} className="rollout-card">
              <div className="rollout-header">
                <strong>{r.firmware_version}</strong>
                <span className={`badge badge-rollout-${r.status}`}>
                  {STATUS_LABEL[r.status] ?? r.status}
                </span>
              </div>
              <div className="progress-bar">
                <div className="progress-applied" style={{ width: `${appliedPct}%` }} />
                <div className="progress-failed" style={{ width: `${failedPct}%` }} />
              </div>
              <div className="rollout-meta">
                <span>
                  {r.applied}/{total} applied · {r.failed} failed
                </span>
                {r.status === "running" && (
                  <button onClick={() => rollbackRollout(r.id)} className="rollback-btn">
                    Roll back now
                  </button>
                )}
              </div>
            </div>
          );
        })}
        {rollouts.length === 0 && <p className="empty">No rollouts started yet.</p>}
      </div>
    </section>
  );
}
