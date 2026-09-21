# IRIS Command Center

**Observe. Investigate. Act—safely.**

A permission-aware, AI-assisted operations console for InterSystems IRIS, built on top of the IRIS SysAdmin REST APIs.

> **Status: Final contest build.** The backend is a real FastAPI application with a working IRIS REST client, a privilege-aware authorization layer, an operation execution framework (authorization → confirmation → execution → post-action verification), OpenTelemetry-style in-memory execution observability (trace/span records) with an optional, feature-flagged IRIS-backed persistence path (off by default), a native-IRIS-audit Investigation view cross-linked with Observability by time, and one real mutating operation. The frontend is a 15-view vanilla HTML/CSS/JS application backed entirely by `/api/iris/*` routes. See [Current Development Status](#current-development-status) below for exactly what exists and what doesn't, and [4-Minute Demo Flow](#4-minute-demo-flow) for how the whole system is meant to be shown together.

---

## Project Vision

InterSystems IRIS administrators and support engineers routinely move between multiple tools and manual API calls to understand what is happening inside a running IRIS environment — checking system health, tracing processes, reviewing security configuration, and investigating incidents. IRIS Command Center brings those workflows into a single, permission-aware operations console: a place to **observe** system state, **investigate** issues with context, and **act** on the environment only through safe, verifiable, explicitly-confirmed operations.

The long-term goal is a web-based command center that:

- Surfaces IRIS system state (namespaces, processes, databases, security configuration, logs) in a readable, unified interface.
- Helps operators investigate incidents by correlating and normalizing information already exposed by IRIS's SysAdmin REST APIs.
- Assists investigation and triage with an AI Assistant, without ever letting it silently perform mutating actions.
- Treats every mutating operation as privileged: authorized, validated, confirmed, and verified — never fired blind.

## Problem Statement

Operating InterSystems IRIS today typically requires administrators to:

- Use the Management Portal for point-in-time visibility, without a unified investigation or correlation view.
- Manually script or call REST endpoints to gather cross-cutting operational data.
- Rely on tribal knowledge of which endpoints require which privileges, with no single source of truth.
- Perform sensitive administrative actions with no consistent, auditable confirmation and verification workflow.

There is no open-source tool that combines a permission-aware operations UI, structured investigation tooling, and optional AI assistance specifically for the IRIS SysAdmin REST API surface, while treating safety and privilege-awareness as first-class design constraints rather than afterthoughts.

## Capabilities

- **Observe (implemented):** Dashboards and detail views for IRIS system info, namespaces, processes, databases, web applications, scheduled tasks, OAuth2 security configuration, journal settings, external language servers, file system access purposes, and wallet collections — all read directly through the IRIS SysAdmin REST APIs via the backend, never fabricated.
- **Investigate (implemented):** The Investigation view searches IRIS's own native security audit log (`GET /v2/security/audit/enabled`, `POST`-then-poll `/v2/security/audit/records`) with optional time/event-type/username/text filters — a real correlation workflow, not a fabricated one. It is cross-linked, by time proximity only (there is no shared ID between the two systems), with the Observability view: a trace's "Investigate audit records" button opens Investigation pre-filtered to a ±30s window around that trace, and an audit record's "Traces" button does the reverse.
- **Act—safely (implemented for one operation):** A privilege-aware operation execution framework gates every mutating action behind backend authorization, privilege validation against the caller's real IRIS session, explicit user confirmation, and post-action verification. One real mutating operation is wired end-to-end today: `journal.update_purge_archived` (toggling the IRIS journal's "Purge Archived Files" setting). The framework is designed to add further operations without changing its core logic, but no others are implemented yet.
- **AI assistance (implemented, not LLM-based):** An "AI Assistant" view answers a fixed set of natural-language questions (system status, process count/list, database status, web app status, task info, and the purge-archived operation) using a small, fully deterministic keyword classifier that routes each message to one of a fixed set of intents (`backend/app/assistant/`) — **no external LLM or AI provider is connected**. It reuses the exact same read-only routes as the rest of the app, and its one supported mutating question still goes through the full authorization/confirmation/execution framework, never a shortcut.
- **Execution observability (implemented):** Every attempted operation — successful or not — is recorded as a structured, OpenTelemetry-style `ExecutionTrace` (spans for authorization/confirmation/execution/verification, with timestamps, durations, statuses, and safe structured attributes; never a credential or token). The Observability view lists and filters these. Storage is in-memory by default (lost on process restart); an optional, off-by-default `persist_traces_to_iris` setting additionally, best-effort persists each trace to a single IRIS global (`^CommandCenterTrace`, capped at 200 entries) via IRIS's Native API — see [Architecture](docs/architecture.md) for how this stays fully additive to the in-memory store and every existing read route.
- **API capability tracking (implemented, both as a document and a live view):** [`docs/api-capability-matrix.md`](docs/api-capability-matrix.md) documents which SysAdmin REST endpoints have been verified against a real IRIS instance, under which privileges, with real observed response shapes (including discrepancies from the spec). The same data is also served live via `GET /api/iris/capabilities` and rendered as the in-app "API Explorer" view, with search and status filters.

## Technology Stack

- **Frontend:** Vanilla HTML, CSS, and JavaScript (no frontend framework). No build step or bundler.
- **Backend:** Python with FastAPI.
- **IRIS integration:** InterSystems IRIS SysAdmin REST APIs, per `spec/mainspec_v2.json`.
- **Deployment:** Docker / Docker Compose — still placeholder configuration only (see [Current Development Status](#current-development-status)); nothing has been containerized yet.

No technology beyond what is listed above is used. Angular and React remain explicitly out of scope for the frontend.

## Security Principles

These principles are enforced by the current implementation, not just aspirational:

1. **No implicit trust.** The backend is the only component that talks to IRIS; the frontend calls only the backend's own `/api/iris/*` routes and holds no IRIS credentials.
2. **Privilege-aware by design.** Every operation registered in `app/authorization/operations.py` declares its required IRIS privilege(s); `app/authorization/service.py`'s `authorize()` checks the caller's actual, IRIS-confirmed privileges (via a live `GET /info` call, never client-supplied claims) before anything proceeds.
3. **Explicit confirmation for mutation.** Every `OperationDefinition` of kind `MUTATING` is required, at construction time, to set `confirmation_required=True` — there is no code path to define a mutating operation that skips this.
4. **Post-action verification.** The execution framework records a post-action verification result for every real execution attempt (`app/execution/models.py`'s `PostActionVerificationResult`).
5. **AI is advisory, not autonomous.** The AI Assistant only reuses existing read-only routes and the same authorization/execution framework for its one mutating capability — it has no separate, unchecked write path.
6. **No fabricated data.** Every view renders real backend responses; unavailable data is shown as unavailable (e.g. "Could not reach IRIS"), never simulated.

See [`docs/authorization-model.md`](docs/authorization-model.md) and [`docs/operation-execution-model.md`](docs/operation-execution-model.md) for the full design.

## Current Development Status

**Implemented:**

- **Backend** (`backend/`): FastAPI app with a real IRIS REST client and session/auth handling (`app/auth/iris_auth.py`), 19 `/api/iris/*` GET routes (15 backed directly by real, IRIS-verified endpoints — see `docs/api-capability-matrix.md`'s 17 verified entries, two of which are internal-only and not separately routed: the login flow and async-task polling — plus 4 Command-Center-native routes: operations registry, AI Assistant query, execution traces, and the capability explorer) plus the one mutating `POST`, a privilege-aware authorization layer, an operation execution framework, OpenTelemetry-style in-memory execution observability with optional IRIS-backed persistence (off by default), and native IRIS audit-log search for Investigation. 151 backend unit tests pass (`backend/tests/`).
- **Frontend** (`frontend/`): a 15-view vanilla JS application — Dashboard, System, Namespaces, Processes, Databases, Web Apps, Tasks, Security, Journal, Operations, AI Assistant, Observability, Extensions (external language servers, file system access purposes, wallet collections), Investigation, and the API Capability Explorer. Every nav item is functional; none are disabled placeholders. A frontend smoke test suite (`tests/test_frontend_smoke.py`) verifies markup, endpoint scoping per view, and that no view sends a mutating HTTP request except the one sanctioned `POST` to the purge-archived route.
- **One real mutating operation:** `journal.update_purge_archived`, executable end-to-end from the Operations view or the AI Assistant, live-verified against a real IRIS 2026.2 instance.
- **CORS for local two-process dev.** The backend sends `CORSMiddleware` headers for `http://localhost:5500` (`backend/app/main.py`), so a frontend served on port 5500 and the backend on port 8000 talk to each other directly — no proxy workaround needed. See [Installation](#installation).

**Not implemented / explicitly out of scope so far:**

- **Docker packaging.** `Dockerfile` and `docker-compose.yml` remain intentionally empty placeholders; nothing has been containerized.
- **Real AI/LLM integration.** The AI Assistant is a deterministic keyword classifier, not a connection to any AI provider; `AI_PROVIDER`/`AI_API_KEY`/`AI_MODEL` in `.env.example` are unread placeholders.
- **A dedicated login/session screen.** The backend authenticates to IRIS as a single configured service account (`IRIS_USERNAME`/`IRIS_PASSWORD` in `backend/.env`) — there is no per-user interactive login flow in this application.
- **Broader mutating-operation coverage.** Only `journal.update_purge_archived` is real; the authorization registry's `delete_task` entry is explicitly illustrative/unimplemented (no route, no handler).
- **IRIS-backed trace persistence, enabled by default.** `persist_traces_to_iris` defaults to `False`; the in-memory store remains the only thing every existing read route/UI reads from either way — see [Architecture](docs/architecture.md).
- **Broader SysAdmin REST API coverage.** 17 of the ~273 operations in `spec/mainspec_v2.json` have been verified against a real instance so far (`docs/api-capability-matrix.md`).

This project is being developed for the **InterSystems Developer Community programming contest**.

## Screenshots

No screenshot is embedded in this README yet, though the application is runnable locally — see [Installation](#installation).

## Demo Video

_Not yet available._

## 4-Minute Demo Flow

The contest demo walks through all four pillars — Observe, Investigate, Act—safely, and the AI Assistant — using one real, live action as the through-line: everything shown is either a live read against the connected IRIS instance, or the single real mutation this project supports, run through its full safety framework.

1. **Dashboard (Observe, ~30s):** live system stat cards (version, namespace/database/process/web-app/task counts) and Recent Activity, sourced from `GET /api/iris/info` and friends plus the in-memory execution trace store — nothing simulated.
2. **AI Assistant (~40s):** a couple of read-only questions (e.g. system status, database status) answered by the deterministic intent classifier, plus a question about the protected journal operation — demonstrating that the assistant can describe a mutating operation without ever being able to execute it via a shortcut.
3. **Operations (Act—safely, ~75s — the centerpiece):** review `journal.update_purge_archived`'s registry metadata and current value, choose a target value, pass through the explicit confirmation step, then execute — showing authorization → confirmation → execution → post-action verification happen for real, against the live IRIS instance, with the verified before/after value displayed.
4. **Observability (~40s):** the trace just produced, expanded to show its four spans (authorization/confirmation/execution/verification) with durations and structured attributes — the OpenTelemetry-style record of exactly what just happened.
5. **Investigation (Investigate, ~35s):** from that same trace, "Investigate audit records" jumps to IRIS's own native security audit log, time-windowed around the action — closing the loop by showing the Command Center's own record and IRIS's independent record of the same event side by side.

Total: ~4 minutes. Every step reads live data or runs the one real, framework-gated mutation — no screen in this flow is backed by mock or seeded data.

## Installation

**Backend:** copy `backend/.env.example` to `backend/.env`, fill in real IRIS connection details, then from `backend/`:

```
.venv\Scripts\activate        # or: source .venv/bin/activate on macOS/Linux
uvicorn app.main:app --reload --port 8000
```

**Frontend:** see [`docs/frontend.md`](docs/frontend.md) — serve `frontend/` as plain static files on port **5500** specifically, e.g. `python -m http.server 5500` from `frontend/`, then open `http://localhost:5500/index.html`. No build step.

**CORS:** the backend's `CORSMiddleware` allows exactly `http://localhost:5500` as an origin (`backend/app/main.py`). Serving the frontend on that port talks to the `:8000` backend with no proxy or extra configuration; serving it on any other port will still show "Could not reach IRIS" in the browser.

## Configuration

See [`.env.example`](./.env.example) (project-level) and [`backend/.env.example`](backend/.env.example) (backend-specific) for configuration keys. IRIS connection details and application host/port are consumed by the backend today. AI provider configuration (`AI_PROVIDER`/`AI_API_KEY`/`AI_MODEL`) remains a placeholder, read by no code — the current AI Assistant needs none of it.

Three additional, optional backend settings (`backend/app/config.py`) control IRIS-backed trace persistence — not present in the `.env.example` templates yet since the feature defaults to off and needs none of them to run:

| Variable | Default | Purpose |
|---|---|---|
| `PERSIST_TRACES_TO_IRIS` | `false` | Enables best-effort, additional persistence of every execution trace to `^CommandCenterTrace` in IRIS. `false` leaves the app's behavior exactly as if this feature didn't exist. |
| `IRIS_NAMESPACE` | `USER` | The IRIS namespace `^CommandCenterTrace` is written into, when enabled. |
| `IRIS_SUPERSERVER_PORT` | `1973` | The Native API (superserver) port to connect to, when enabled — `1973` matches `icc-iris-dev`'s host-mapped port (Docker publishes the container's standard `1972` to host port `1973`; see `docker ps`). |

---

## Documentation

- [Product Requirements](docs/product-requirements.md)
- [Architecture](docs/architecture.md)
- [Authorization Model](docs/authorization-model.md)
- [Operation Execution Model](docs/operation-execution-model.md)
- [API Capability Matrix](docs/api-capability-matrix.md)
- [Frontend](docs/frontend.md)

## Implementation Status Notice

This project is a work in progress, but a substantial part of it is real and runnable today: see [Current Development Status](#current-development-status) above for a precise, code-verified account of what exists versus what's still planned. Nothing described as "implemented" in this README is simulated — every implemented view and route is backed by real code and, where noted, live-verified against a running IRIS instance.
