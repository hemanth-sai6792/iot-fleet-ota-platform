# Home & factory automation platform

A backend + console for a home-automation company serving three customer
segments — household, showroom, and factory — modeled on how a real company
in this space is structured, not a generic IoT demo. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design rationale,
design-pattern selection, and data model.

## What this is

- **Household/showroom**: rooms, scenes, sensor/time/voice-triggered rules,
  Alexa Smart Home integration — devices get added to rooms, rooms and
  scenes get named, and those names are validated against Alexa's
  voice-discovery constraints at creation time.
- **Factory**: a device → unit → division hierarchy for electrical
  appliances. Electricity is metered at the unit and division level only
  (not per device — individually metering every appliance is cost-prohibitive
  at factory scale). Units and divisions each have a master power switch that
  cascades to every device inside them, with a task-safety interlock: a
  device mid-operation (a welder mid-weld, a press mid-stroke) blocks the
  cascade and surfaces a warning instead of being silently force-stopped.
- **One React console**, not a mobile app — desktop/tablet is the real
  constraint for factory floor use, so a responsive web app is genuinely
  sufficient here.

## Architecture, briefly

Modular monolith, layered ports-and-adapters:

```
API (FastAPI routers) → application services (app/control.py)
                       → domain logic (app/household.py, app/factory.py) — pure, no I/O
                       → adapters (Postgres repos via asyncpg, AlexaAdapter, MQTT)
```

Two runtime processes, one docker-compose stack:
- **api** — REST + WebSocket, serves the React console
- **core-engine** — async MQTT ingestion, shadow reconciliation (desired vs.
  reported state, same mechanism whether it's a lamp or a factory motor),
  and the usage/threshold/meter-reconciliation monitor

Devices are the only physical MQTT clients. Units and divisions are logical
groupings — their "master switch" is a cascade command computed by the API,
not a separate physical MQTT identity — except for their meters, which do
publish real readings.

## Running it

```bash
docker compose up -d --build
```

- API + docs: http://localhost:8000/docs
- Console: http://localhost:5173
- The simulator bootstraps one sample household site (3 rooms, 4 devices)
  and one sample factory site (1 division, 2 units, 6 devices — including a
  welder and a press machine that periodically enter a non-interruptible
  "running_task" state, so the cascade interlock has something real to
  block) and starts publishing over MQTT immediately.

### Try the cascade interlock

```bash
# find the "Assembly Line 1" unit id from GET /units?division_id=..., then:
curl -X POST http://localhost:8000/units/<unit_id>/power \
  -H 'Content-Type: application/json' -d '{"desired_power": "off"}'
```

If the welder is mid-task, it comes back in `blocked` with a message naming
the device, unit, and division — everything else in the unit still powers
off. Retry with `"force": true` to override (logged to `/audit` either way).

### Tests

```bash
cd backend && pip install -r requirements.txt && pytest tests/
```

Covers the pure logic that matters most: Alexa name validation, rule-trigger
dispatch (`test_household.py`), cascade planning + meter reconciliation
(`test_factory.py`), the Alexa discovery/directive adapter (`test_alexa.py`),
and shadow-state diffing (`test_shadow.py`) — no broker or database required.

## CI/CD

`jenkins/Jenkinsfile` — install, test, a SonarQube gate scoped to the async
control-plane modules (`ingestion.py`, `shadow.py`, `control.py`,
`usage_monitor.py` — where concurrency bugs actually bite when real
appliances are on the other end), then image builds.

## What's real vs. stubbed

Real: the cascade/interlock logic, shadow reconciliation, meter
reconciliation and threshold alerting, the Alexa name-validation and
discovery/directive adapter shape, the audit trail.

Stubbed/out of scope, on purpose:
- **Node-RED** isn't part of this build — the simulator stands in for
  wherever Node-RED and real hardware would normally sit. What's real is the
  MQTT topic contract (`devices/{id}/state/...`) it would integrate against.
- **Alexa** integration is a payload-shape adapter, not a registered Skill —
  no Login-with-Amazon, no Lambda endpoint.
- **Remote access/on-site fallback** is a documented operational model
  (see ARCHITECTURE.md), not implemented infrastructure — no VPN/tunnel here.
- No Kubernetes, no Kafka — Postgres + asyncio + a lightweight in-process
  pub/sub is the whole story at this scale.
