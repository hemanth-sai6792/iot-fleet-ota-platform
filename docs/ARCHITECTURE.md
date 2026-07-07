# Architecture

## Structure: modular monolith, ports & adapters

One backend engineer, one deploy unit — a microservices split would be pure
ops overhead with no payoff at this scale. But it's not a flat CRUD app
either: Alexa, Node-RED/devices, and Postgres are three volatile external
integrations, and the point of hexagonal layering is that none of them leak
into core domain logic.

```
API layer      → FastAPI routers (app/main.py)
Application    → use-case services (app/control.py — the only place that
                  touches MQTT for a desired-state push)
Domain         → pure logic, no I/O (app/household.py, app/factory.py)
Adapters (out) → Postgres via asyncpg, AlexaAdapter (app/alexa.py), MQTT
```

The domain layer never imports asyncpg, aiomqtt, or an Alexa SDK — only the
adapters do. This is what lets Alexa be swapped for another voice platform,
or Node-RED for something else, without touching cascade or scene logic.

## Design pattern selection

| Pattern | Where | Why this one |
|---|---|---|
| **Adapter** | `AlexaAdapter` (`app/alexa.py`) | Isolates Alexa's naming/discovery/directive shapes so the domain model stays clean |
| **Repository** (via asyncpg queries in `app/main.py`/`app/control.py`) | Data access | Swappable for a test double; domain/application code never writes SQL directly |
| **Strategy** | `app/household.py::evaluate_rule` | Trigger types (time/sensor/voice) dispatch to independent evaluators — new trigger types don't grow an `if/elif` chain |
| **Composite** | Division → Unit → Device (`app/factory.py::plan_cascade_command`) | Usage rollups and cascade commands are naturally recursive; one planning function serves all three hierarchy levels since they're structurally the same "scope with children" |
| **Observer/pub-sub** | Device state change → shadow reconciliation, live WebSocket broadcast | Decouples "a device changed" from "who needs to know" |
| **State machine** (explicit) | `devices.status`: online / offline / fault / running_task | A fixed transition set instead of loose strings — catches invalid states at write time via a DB `CHECK` constraint |

## Data model

**Shared core**: `sites` (household / showroom / factory) → `devices`
(status, task_interruptible, desired_state, reported_state — belongs to
*either* a room *or* a unit, never both, enforced by a DB constraint).

**Household/showroom**: `rooms`, `scenes` + `scene_devices` (many-to-many,
target state per device), `rules` (trigger_type/trigger_config/action).
Room and scene names are validated against Alexa's voice-discovery
constraints (`validate_alexa_name`) at creation time — rejected immediately
with a clear error, not discovered later when Alexa's device discovery
silently skips a bad name.

**Factory**: `divisions` → `units` → `devices`. Both divisions and units
have their own `desired_state`/`reported_state` (they're "Controllable" too
— the master-switch concept) but are *not* independent physical MQTT
clients; their power state is a computed cascade over their child devices.
`usage_readings` is metered at **unit and division granularity only**
(partitioned by day, same pattern as any high-volume telemetry table) —
individually metering every appliance is cost-prohibitive at factory scale,
and capping ingestion cardinality here is also what keeps this simple at
scale, not just cheaper. `meter_reconciliations` compares a division's main
meter against the sum of its units' sub-meters — a persistent mismatch
usually means sensor drift or a wiring fault, not a real usage anomaly.
`fault_logs` stay per-device (control/status granularity is finer than
metering granularity). `audit_log` records every remote/cross-site action;
`reason` is enforced as mandatory at the API layer for cross-site
troubleshooting access, not for a site's own local operators.

## The cascade + task-safety interlock

`Device`, `Unit`, and `Division` share one `Controllable` shape. Turning off
a unit or division recursively targets every device inside it, but first
checks each device's status: a device in `running_task` (mid-weld,
mid-press-stroke — not safely interruptible right now) is held back and
returned as a `blocked` entry naming the device, its unit, and its division,
rather than being force-stopped silently. The operator can wait or force —
a forced override is logged to the audit trail.

## Low-latency / large-scale reasoning

The backend is **not** in the hard real-time safety path — breaker hardware
trips on overload regardless of software. The backend's job is near-real-time
visibility and orchestration:

- **Edge-first control**: in a real deployment, Node-RED/an on-site hub
  executes control loops locally; the cloud backend distributes config down
  and pulls aggregates up. Cloud latency or an outage never blocks an
  on-site action.
- **Async, isolated ingestion** (one aiomqtt session, bounded per-message
  work) so one slow device/meter can't stall the others — this is exactly
  what the SonarQube gate is scoped to protect.
- Metering only at unit/division granularity caps ingestion volume by
  construction, which is what keeps this simple at real factory scale
  without Kafka/k8s-level infrastructure.

## Awareness: what's adjacent but not built here

| Area | The honest scope |
|---|---|
| **Node-RED** | Not rebuilt. The MQTT topic contract (`devices/{id}/state/reported`, `.../state/desired`, `.../heartbeat`, `units\|divisions/{id}/usage`) is what any flow-engine or real hardware integrates against. The simulator plays that role for this build. |
| **Server & remote access** | Real deployments run an on-site hub (Node-RED + an agent) reachable via a reverse tunnel/VPN for remote troubleshooting; on-site manual restart is the fallback when remote access itself is down. Not implemented here. |
| **Alexa setup** | A real integration needs a registered Smart Home Skill, Login-with-Amazon account linking, and an AWS Lambda endpoint. `app/alexa.py` is the payload-translation boundary that endpoint would call into — the part worth being precise about in an interview, not the OAuth plumbing. |
| **Regional-language voice commands** | Sits on top of Alexa's own STT — not something controllable at the skill level, which is the honest reason this is hard, not a shortcoming of this codebase. |
| **Factory live data, two audiences** | The on-site dashboard needs data even if cloud connectivity drops (local-first); the company-side view gets it via sync-when-online. Only the single-site case is built here. |
| **Testing beyond pytest** | Staging chaos tests (force device failures, confirm the cascade interlock and reconciliation degrade safely) sit above this unit-test suite — QA-owned in a real org. |
| **DevOps beyond Jenkins/Sonar** | Container registry, secrets management, monitoring/alerting (Prometheus/Grafana-class tooling) — this repo emits Dockerfiles and signals, not the infrastructure that operates them. |
