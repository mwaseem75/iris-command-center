# IRIS Command Center

**Observe. Investigate. Act—safely.**

A permission-aware, AI-assisted operations and investigation platform for InterSystems IRIS, built on top of the IRIS SysAdmin REST APIs.

> **Status: Phase 0 — Project Foundation.** This repository currently contains project documentation and scaffolding only. No backend, frontend, authentication, or AI functionality has been implemented yet. See [Current Development Status](#current-development-status) below.

---

## Project Vision

InterSystems IRIS administrators and support engineers routinely move between multiple tools and manual API calls to understand what is happening inside a running IRIS environment — checking system health, tracing processes, reviewing security configuration, and investigating incidents. IRIS Command Center aims to bring those workflows into a single, permission-aware operations console: a place to **observe** system state, **investigate** issues with context, and **act** on the environment only through safe, verifiable, explicitly-confirmed operations.

The long-term goal is a web-based command center that:

- Surfaces IRIS system state (namespaces, processes, databases, security configuration, logs) in a readable, unified interface.
- Helps operators investigate incidents by correlating and normalizing information already exposed by IRIS's SysAdmin REST APIs.
- Optionally assists investigation and triage with AI, without ever letting AI silently perform mutating actions.
- Treats every mutating operation as privileged: authorized, validated, confirmed, and verified — never fired blind.

## Problem Statement

Operating InterSystems IRIS today typically requires administrators to:

- Use the Management Portal for point-in-time visibility, without a unified investigation or correlation view.
- Manually script or call REST endpoints to gather cross-cutting operational data.
- Rely on tribal knowledge of which endpoints require which privileges, with no single source of truth.
- Perform sensitive administrative actions with no consistent, auditable confirmation and verification workflow.

There is no open-source tool that combines a permission-aware operations UI, structured investigation tooling, and optional AI assistance specifically for the IRIS SysAdmin REST API surface, while treating safety and privilege-awareness as first-class design constraints rather than afterthoughts.

## Planned Capabilities

These capabilities are **planned**, not implemented. They describe the intended scope of the project as it moves through future phases.

- **Observe:** Unified dashboards for IRIS system health, namespaces, processes, databases, and web applications, built on the IRIS SysAdmin REST APIs.
- **Investigate:** Tools to search, filter, and correlate system and security events/logs to support incident investigation.
- **Act—safely:** A privilege-aware operation layer for mutating actions, gated behind backend authorization checks, privilege validation, explicit user confirmation, and post-action verification.
- **AI assistance (optional):** An AI layer that can help interpret system state and suggest next steps, operating strictly through a controlled tool registry — never with direct, unconfirmed write access.
- **API capability tracking:** A living capability matrix documenting which SysAdmin REST endpoints have been verified, against which IRIS versions, and under which privileges.

## Planned Technology Stack

- **Frontend:** Vanilla HTML, CSS, and JavaScript (no frontend framework).
- **Backend:** Python with FastAPI.
- **IRIS integration:** InterSystems IRIS SysAdmin REST APIs (as defined in the project's API specification, `mainspec_v2.json`, once added to `spec/`).
- **Deployment:** Docker / Docker Compose (placeholder configuration only at this stage).

No technology beyond what is listed above is currently planned. Angular and React are explicitly out of scope for the frontend.

## Security Principles

These principles govern the design of every future phase of this project:

1. **No implicit trust.** The backend independently authorizes and validates every request; the frontend is never a trust boundary.
2. **Privilege-aware by design.** Every operation, especially mutating ones, is checked against the acting user's actual IRIS privileges before execution.
3. **Explicit confirmation for mutation.** No mutating action executes without an explicit, unambiguous user confirmation step.
4. **Post-action verification.** After a mutating action executes, the system verifies the resulting state rather than assuming success.
5. **AI is advisory, not autonomous.** Any future AI assistance operates through a constrained, auditable tool registry and is never granted silent write access.
6. **No fabricated data.** The project will not simulate API responses, metrics, or screenshots as if they were real system output.

## Current Development Status

**Phase 0 — Project Foundation.** This phase establishes documentation, repository structure, and planning artifacts only. Explicitly out of scope for this phase: backend functionality, frontend screens, authentication, AI functionality, and any runnable application code.

This project is being developed for the **InterSystems Developer Community programming contest**.

## Screenshots

_Not yet available. This project has no frontend implementation yet. Screenshots will be added once Phase 0 restrictions are lifted and UI work begins._

## Demo Video

_Not yet available._

## Installation

_Not yet available. Implementation has not started — there is no application to install or run yet._

## Configuration

_Not yet available. See [`.env.example`](./.env.example) for the placeholder configuration keys planned for future phases (IRIS connection details, AI provider settings, application host/port). None of these are consumed by any code yet._

---

## Documentation

- [Product Requirements](docs/product-requirements.md)
- [Architecture (planned)](docs/architecture.md)
- [API Capability Matrix](docs/api-capability-matrix.md)

## Implementation Status Notice

**This project is a work in progress.** As of Phase 0, no backend, frontend, authentication, or AI functionality exists. All capabilities described in this README are planned, not delivered. Please do not expect a runnable application at this stage.
