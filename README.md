# IoT Device Fleet & OTA Management Platform

A staged/canary firmware-rollout platform for a fleet of IoT devices, built
around a device-shadow (desired vs. reported state) pattern with async MQTT
ingestion and auto-rollback. This is a scoped, one-day portfolio build — see
[What's simulated vs. real](#whats-simulated-vs-real) for the honest cuts.

## Architecture

```
 [Device Simulator]  --MQTT-->  [Mosquitto broker]
  (N asyncio clients)                  |
                                        v
                          [core-engine: aiomqtt ingestion,
                           shadow reconciliation, rollout monitor]
                                        |
                                        v
                                  [Postgres]
                              (devices, partitioned
                               telemetry, rollouts)
                                        ^
                                        |
                       [FastAPI: REST + WebSocket] <---> [React dashboard]
```

- **core-engine** (`backend/app/engine_main.py`) — one asyncio process running
  three logically separate loops concurrently: MQTT ingestion, device-shadow
  reconciliation (diff desired vs. reported, push corrections), and the OTA
  rollout monitor (failure-rate check, auto-rollback). Kept as one process for
  this build; each loop is independent and could scale out on its own.
- **api** (`backend/app/main.py`) — FastAPI REST for device
  provisioning/rollout control, plus a WebSocket that pushes a fleet snapshot
  to the dashboard on a fixed tick.
- **Postgres** — device registry + telemetry, with telemetry **range-partitioned
  by day** (`backend/init.sql`) so retention and recent-data queries stay cheap
  as the table grows, instead of one unbounded row-per-reading table.
- **simulator** (`backend/simulator/device_simulator.py`) — spawns N virtual
  devices as concurrent asyncio/MQTT clients. This is how the ingestion path
  and rollout engine get exercised at scale without owning real hardware.
- **frontend** (`frontend/`) — React + Vite dashboard: live fleet table and
  rollout panel with progress bars and a manual rollback button.

## Running it

```bash
docker compose up -d --build
```

- API: http://localhost:8000 (docs at `/docs`)
- Dashboard: http://localhost:5173
- Mosquitto: `localhost:1883`
- Postgres: `localhost:5432` (user/pass `iot`/`iot`, db `iot_fleet`)

The simulator registers 25 virtual devices on startup and starts publishing
telemetry/heartbeats immediately — the dashboard should show them going
online within a few seconds.

### Try a rollout

```bash
curl -X POST http://localhost:8000/rollouts \
  -H 'Content-Type: application/json' \
  -d '{"firmware_version": "1.1.0", "canary_percent": 20, "failure_threshold_percent": 20}'
```

Watch it complete in the dashboard's rollout panel. To see the auto-rollback
path, bump the simulator's `FAILURE_RATE` env var (0.0-1.0) before starting a
rollout — once enough devices report `update_status: failed`, the rollout
monitor halts it and reverts the affected devices' desired state.

### Tests

```bash
cd backend && pip install -r requirements.txt && pytest tests/
```

Tests cover the two pieces of pure logic that matter most: shadow-state diffing
(`test_shadow.py`) and canary selection / rollback-threshold evaluation
(`test_rollout.py`) — no broker or database required.

## CI/CD

- `jenkins/Jenkinsfile` — app CI: install, test, SonarQube quality gate
  (scoped to `ingestion.py` / `shadow.py` / `rollout.py` / `engine_main.py` —
  the concurrency-bug risk is in the async loops, not repo-wide style), build
  images.
- `jenkins/Jenkinsfile.firmware` — the OTA-specific pipeline: builds a firmware
  bundle from `firmware/`, checksums it, stages it, and calls the same
  `/rollouts` API the dashboard uses to kick off a canary rollout.
- `sonar-project.properties` — quality-gate config for the ingestion path.

## What's simulated vs. real

Real: async MQTT ingestion, shadow reconciliation, canary rollout selection,
auto-rollback on failure-rate threshold, day-partitioned Postgres telemetry,
FastAPI WebSocket push, Jenkins pipelines as actual pipeline-as-code.

Simulated/simplified, on purpose, to keep this buildable in a day:
- No real hardware — devices are asyncio/MQTT clients.
- "Firmware signing" is a SHA-256 checksum, not real code-signing/PKI.
- No Kubernetes — single `docker-compose` stack.
- No auth beyond CORS wide-open (not the point of the demo).
- Dashboard refresh is a 1.5s server-side poll broadcast over WebSocket, not
  Postgres `LISTEN`/`NOTIFY` — simpler and plenty fast for a fleet dashboard.
