# IRIS Command Center

**Observe. Investigate. Act—safely.**

A permission-aware, AI-assisted operations console for InterSystems IRIS, built on top of the IRIS SysAdmin REST APIs.

> **Status: Core platform implemented.** The backend is a real FastAPI application with a working IRIS REST client, a privilege-aware authorization layer, an operation execution framework (authorization → confirmation → execution → post-action verification), in-memory execution observability (trace/span records), and one real mutating operation. The frontend is a 13-view vanilla HTML/CSS/JS application backed entirely by `/api/iris/*` routes. See [Current Development Status](#current-development-status) below for exactly what exists and what doesn't.

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
- **Investigate (partially planned):** No dedicated log/event search or cross-source correlation view exists yet. Today's views are per-capability snapshots (e.g. Processes, Journal), not an incident-investigation workflow.
- **Act—safely (implemented for one operation):** A privilege-aware operation execution framework gates every mutating action behind backend authorization, privilege validation against the caller's real IRIS session, explicit user confirmation, and post-action verification. One real mutating operation is wired end-to-end today: `journal.update_purge_archived` (toggling the IRIS journal's "Purge Archived Files" setting). The framework is designed to add further operations without changing its core logic, but no others are implemented yet.
- **AI assistance (implemented, not LLM-based):** An "AI Assistant" view answers a fixed set of natural-language questions (system status, process count/list, database status, web app status, task info, and the purge-archived operation) using a small, fully deterministic keyword classifier (`backend/app/assistant/`) — **no external LLM or AI provider is connected**. It reuses the exact same read-only routes as the rest of the app, and its one supported mutating question still goes through the full authorization/confirmation/execution framework, never a shortcut.
- **API capability tracking (implemented, hand-maintained):** [`docs/api-capability-matrix.md`](docs/api-capability-matrix.md) documents which SysAdmin REST endpoints have been verified against a real IRIS instance, under which privileges, with real observed response shapes (including discrepancies from the spec). This is a maintained document, not a live in-app view.

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

- **Backend** (`backend/`): FastAPI app with a real IRIS REST client and session/auth handling (`app/auth/iris_auth.py`), 13 read-only `/api/iris/*` routes backed by real, verified IRIS endpoints (14 IRIS-side endpoints verified in total, including the internal login flow — see `docs/api-capability-matrix.md`), a privilege-aware authorization layer, an operation execution framework, in-memory execution observability, and the AI Assistant's read/query route. 121 backend unit tests pass (`backend/tests/`).
- **Frontend** (`frontend/`): a 13-view vanilla JS application — Dashboard, System, Namespaces, Processes, Databases, Web Apps, Tasks, Security, Journal, Operations, AI Assistant, Observability, and Extensions (external language servers, file system access purposes, wallet collections). Every nav item is functional; none are disabled placeholders. A frontend smoke test suite (`tests/test_frontend_smoke.py`) verifies markup, endpoint scoping per view, and that no view sends a mutating HTTP request except the one sanctioned `POST` to the purge-archived route.
- **One real mutating operation:** `journal.update_purge_archived`, executable end-to-end from the Operations view or the AI Assistant, live-verified against a real IRIS 2026.2 instance.

**Not implemented / explicitly out of scope so far:**

- **Docker packaging.** `Dockerfile` and `docker-compose.yml` remain intentionally empty placeholders; nothing has been containerized.
- **Real AI/LLM integration.** The AI Assistant is a deterministic keyword classifier, not a connection to any AI provider; `AI_PROVIDER`/`AI_API_KEY`/`AI_MODEL` in `.env.example` are unread placeholders.
- **A dedicated login/session screen.** The backend authenticates to IRIS as a single configured service account (`IRIS_USERNAME`/`IRIS_PASSWORD` in `backend/.env`) — there is no per-user interactive login flow in this application.
- **A log/event investigation view.** No cross-source log search or correlation tooling exists yet (see [`docs/product-requirements.md`](docs/product-requirements.md)'s planned screens).
- **Broader mutating-operation coverage.** Only `journal.update_purge_archived` is real; the authorization registry's `delete_task` entry is explicitly illustrative/unimplemented (no route, no handler).
- **A live, in-app capability-matrix explorer.** The matrix exists only as the hand-maintained `docs/api-capability-matrix.md`; 14 of the ~273 operations in `spec/mainspec_v2.json` have been verified against a real instance.

This project is being developed for the **InterSystems Developer Community programming contest**.

## Screenshots

No screenshot is embedded in this README yet, though the application is runnable locally — see [Installation](#installation).

## Demo Video

_Not yet available._

## Installation

**Backend:** copy `backend/.env.example` to `backend/.env`, fill in real IRIS connection details, then from `backend/`:

```
.venv\Scripts\activate        # or: source .venv/bin/activate on macOS/Linux
uvicorn app.main:app --reload --port 8000
```

**Frontend:** see [`docs/frontend.md`](docs/frontend.md) — any static file server works, e.g. `python -m http.server` from `frontend/`, serving `frontend/index.html`. No build step.

**Known local-dev limitation:** the backend does not send CORS headers, so running the frontend and backend as two separate local processes on different ports/origins will show "Could not reach IRIS" in the browser even though both are up — see `docs/frontend.md`'s "Known Limitation" for the currently-undecided fix (backend CORS middleware vs. same-origin serving).

## Configuration

See [`.env.example`](./.env.example) (project-level) and [`backend/.env.example`](backend/.env.example) (backend-specific) for configuration keys. IRIS connection details and application host/port are consumed by the backend today. AI provider configuration (`AI_PROVIDER`/`AI_API_KEY`/`AI_MODEL`) remains a placeholder, read by no code — the current AI Assistant needs none of it.

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
