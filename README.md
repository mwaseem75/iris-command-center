# ✨ IRIS Command Center

**Observe. Investigate. Act—safely.**

A modern operational console for **InterSystems IRIS** that brings monitoring, administration, investigation, security, visibility, issue resolution, and operational tracing into one place.
It combines live IRIS system information with controlled administrative workflows, native audit investigation, structured execution traces, security visibility, and **IRIS Ops Skill** — a reusable, safety-oriented AI operations capability that explains live IRIS issues and resolves a closed set of approved problems only through deterministic planning, explicit confirmation, authorization, verification and tracing.
<p align="center">
<img width="2048"  alt="image" src="https://github.com/user-attachments/assets/be3beb83-ba53-41a1-8e78-53ff8e5c5a26" />
</p>
<p align="center">
  <a href="https://www.intersystems.com/"><img src="https://img.shields.io/badge/Platform-InterSystems%20IRIS-009688?style=flat-square" alt="InterSystems IRIS"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/Backend-FastAPI-009688?style=flat-square" alt="FastAPI"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Language-Python-3776AB?style=flat-square" alt="Python"></a>
  <a href="https://developer.mozilla.org/en-US/docs/Web/JavaScript"><img src="https://img.shields.io/badge/Frontend-Vanilla%20JavaScript-F7DF1E?style=flat-square" alt="Vanilla JavaScript"></a>
  <a href="https://www.intersystems.com/resources/technology/vector-search/"><img src="https://img.shields.io/badge/Vector%20Search-IRIS%20Vector%20Search-6C4AB6?style=flat-square" alt="IRIS Vector Search"></a>
  <a href="https://www.intersystems.com/"><img src="https://img.shields.io/badge/Embedded%20Python-IRIS%20Embedded%20Python-3776AB?style=flat-square" alt="IRIS Embedded Python"></a>
  <a href="https://www.docker.com/"><img src="https://img.shields.io/badge/Deployment-Docker-2496ED?style=flat-square" alt="Docker"></a>
  <a href="https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GIPM"><img src="https://img.shields.io/badge/Packaging-ZPM%20%2F%20IPM-7B61FF?style=flat-square" alt="ZPM / IPM"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="MIT"></a>
</p>

---

## 🏗️ Architecture

<img width="1536" alt="image" src="https://github.com/user-attachments/assets/6038941b-2ae9-4529-bcc1-1db50f110074" />
<img width="1983" alt="image" src="https://github.com/user-attachments/assets/4cdb4abf-672a-432c-857b-c862655b9717" />

---
## 🏆 IRIS Ops Skill — What Makes It Different

IRIS Ops Skill turns IRIS Command Center from an operational dashboard into a
**safety-oriented AI operations capability for InterSystems IRIS**.

It is not an unrestricted AI agent connected directly to IRIS. The Copilot operates
inside a deterministic, server-side safety boundary:

**Ask → Detect → Explain → Plan → Confirm → Authorize → Execute → Verify → Trace**

### Key Enhancements

| Enhancement | What it provides |
|---|---|
| 🧩 **Closed Capability Catalog** | A single allowlist of approved AI operations. The Copilot cannot invent or execute arbitrary operations. |
| 📋 **Rich Capability Metadata** | Each capability declares examples, constraints, verification and undo information, while privileges and risk come from the existing operation registry. |
| ⏱️ **Task Catalog** | Ask natural-language questions about live IRIS tasks, including suspended tasks, errors, schedules and run-as users — completely read-only. |
| 🔎 **Capability Discovery** | A read-only API exposes the currently approved capabilities and their metadata without exposing handlers or implementation details. |
| 🧵 **Structured Execution Trace** | Planning and execution produce linked `copilot.plan` and `copilot.execute` traces connected to the underlying operation trace. |
| 🛡️ **Structured Failure States** | Rejections and failures use machine-readable codes such as `authorization_failed`, `resource_protected`, `verification_failed` and `issue_still_detected`. |
| 🔐 **Defense in Depth** | AI output is only a proposal. Parameters are rebuilt server-side, authorization is rechecked, explicit confirmation is required, and every mutation is verified. |

### Why this matters

The Copilot is not an unrestricted AI agent with an IRIS connection.
It is an **issue-aware, allowlisted operations layer** built on top of the
Command Center's existing authorization, execution and observability
frameworks.

---

# 🧭 Features at a Glance

| Area | What you can do |
|---|---|
| 📊 **Dashboard** | View live system state, databases, processes, web apps, tasks, resources, alerts, Issues & Recommendations, and recent activity |
| 🩺 **Health Center** | Review overall health and assessment coverage across six categories, with live Current Activity and an informational Performance Snapshot |
| 🩺 **Issue Resolver** | Detect supported issues from live IRIS evidence, distinguish resolvable and detection-only issues, define custom detection rules, investigate or resolve safely, verify results, and follow the execution trace |
| 🗂️ **Namespaces** | Explore namespaces, relationships, and create namespaces safely |
| 💾 **Databases** | Inspect databases, storage, integrity, and perform controlled create, mount, and dismount workflows |
| ⚙️ **Processes** | Search, filter, and investigate live IRIS processes |
| 🌐 **Web Applications** | Inspect configuration, REST applications, sessions, enable/disable apps, and update descriptions |
| 🔍 **REST API Explorer** | Explore generated REST API definitions, endpoints, methods, parameters, and implementation details |
| ⏱️ **Tasks** | Monitor live task state, upcoming runs, schedules, and most recent run information, with task details and supported Run Now workflows |
| 🔐 **Security** | Explore users, roles, resources, authentication posture, wallets, X.509, and OAuth2 |
| 🔌 **Extensions & Integrations** | Inspect external language servers, filesystem access purposes, and wallet integration metadata |
| 🔎 **Investigation** | Search the native IRIS security audit trail and relate activity to Command Center traces |
| 👁️ **Observability** | Inspect structured execution traces and optionally persist them inside IRIS |
| 🤖 **AI Assistant / IRIS Ops Skill** | Issue-aware AI operations over live IRIS data with a closed capability catalog, read-only Task Catalog, explicit confirmation, server-side authorization, structured execution traces, and machine-readable failure states |
| 🔍 **Vector Search** | Search an IRIS-persisted operational knowledge corpus using IRIS Vector Search |
| 🐍 **Embedded Python** | Inspect live diagnostics from IRIS Embedded Python |
| 🎬 **Demo Activity** | Demonstrate controlled operations and an intentional, reversible demo issue, with verification, restoration, and execution tracing |

---

# 🤖 IRIS Ops Skill — Issue-aware Copilot

**IRIS Ops Skill** is a reusable, safety-oriented AI operations capability for InterSystems IRIS. It answers operational questions from live, read-only IRIS evidence and can resolve a small, closed set of approved problems — but only through a deterministic plan, explicit confirmation, server-side authorization, the existing operation executor and post-change verification, with every step traced.

It is not a separate chatbot: it is surfaced through the existing **AI Assistant** page and reuses the same backend services, operation registry, authorization, execution framework and observability as the rest of Command Center.

```mermaid
flowchart LR
    D[Detect<br/>Issue Resolver] --> E[Explain<br/>Copilot answer]
    E --> P[Plan<br/>catalog + detected issue]
    P --> C[Confirm<br/>explicit button]
    C --> A[Authorize<br/>server-side]
    A --> X[Execute<br/>existing operation]
    X --> V[Verify<br/>handler + issue gone]
```

**Detect → Explain → Plan → Confirm → Authorize → Execute → Verify**

### How the Copilot works

1. **Deterministic intent classification.** Every request is classified on the backend as an issue investigation, a health question, a read-only query, a resolution (change) request, or unknown. No model decides the intent.
2. **Read-only IRIS context.** Answers are built from a bounded snapshot of live data read through existing read-only routes: system info, databases, processes, web applications, tasks and the Issue Resolver's active issues (at most 10 items per source, long text capped). Gathering context never writes to IRIS.
3. **Structured responses.** A local, deterministic, rule-based provider returns a structured answer — `answer`, `observations`, `proposed_action`, `requires_confirmation` — with no external service or API key. Its output is descriptive; a proposed action is only a proposal.
4. **Safety/planning gateway.** Deterministic backend code turns a proposal into a plan only for an approved capability. For issue-backed operations, the request's name only *selects* one currently detected issue; the plan's target and parameters are built from that issue and the Issue Resolution Catalog, never from the user's text.
5. **Authorization and explicit confirmation.** Only the **Confirm & Execute** button confirms a plan; typing "yes" in the chat does not. Privileges are checked on the server from the IRIS session and checked again when the operation runs.
6. **Controlled execution and verification.** The plan runs through the existing operation executor and handler. Success requires the handler's post-action verification *and* the Copilot's own check — the Issue Resolver no longer reports the issue, or the journal setting reads back as requested.

### Closed capability catalog

The Copilot can only plan and run operations listed in one closed catalog (`backend/app/copilot/capabilities.py`). Planning, plan validation and execution all read it; anything not listed — including other operations the Command Center supports on its own pages — is refused.

| Capability | Title | Resolves | Example request | Verification status |
|---|---|---|---|---|
| `journal.update_purge_archived` | Set journal PurgeArchived | direct setting request | "Enable PurgeArchived" | ✅ Live-verified on IRIS 2026.2 |
| `database.mount` | Mount a dismounted database | `database_dismounted` | "Mount database IPM" | ✅ Live-verified on IRIS 2026.2 (IPM mounted, issue cleared, resolution history recorded) |
| `web_app.set_enabled` (disable only) | Disable a web application whose namespace is missing | `web_app_namespace_missing` | "Disable web app /csp/example" | 🧪 Covered by automated tests; **not yet live-verified** |

#### Example — controlled administrative action

A natural-language request does not execute an IRIS mutation directly. The Copilot
first produces a deterministic proposal and requires explicit user confirmation
before authorization and execution.

> **"Enable PurgeArchived."**

<img width="1685" alt="image" src="https://github.com/user-attachments/assets/5331359d-b87c-46fb-8633-86ef70d3b42c" />

*The Copilot proposes the approved operation and requires explicit confirmation before execution.*

The catalog is validated when the backend starts; a misconfigured entry stops startup instead of failing at runtime. Every capability must be a registered mutation in the operation registry that requires confirmation, and each issue-backed capability must match the operation the Issue Resolution Catalog uses for that issue.

### Capability metadata and discovery

Each capability carries descriptive metadata: a **title**, **example requests**, the Copilot's own **constraints** (for example *"disable only"* or *"always mounted read-write"*), a **verification** description (what must hold before success is reported) and an **undo** hint.

`GET /api/iris/copilot/capabilities` lists the catalog read-only. Privileges, risk level and the confirmation rule are read from the operation registry, and the issue title and severity from the Issue Resolution Catalog, at request time — nothing is copied. Handlers and parameter models are never exposed.

### Task catalog (read-only)

The Copilot answers task questions from the existing task overview — for example *"Which tasks are suspended?"* or *"Which tasks run as _SYSTEM?"*:

- **Inventory and state:** name, type, namespace, state (Running / Not Running / Suspended, read from each task's `/v2/task/info`), suspended flag, error text (capped), last and next run.
- **Task details:** run-as user, schedule fields as IRIS reports them (TimePeriod, every, DailyFrequency, DailyStartTime) and suspend-on-error. These are read from `GET /v2/task` only when the question asks about them.
- **Bounded:** at most 10 tasks are included, and summaries say when they cover only the tasks shown. If one task's info or detail can't be read, that task is still listed with those fields empty.

#### Example — natural-language Task Catalog query

The Copilot can inspect live IRIS task state without being granted permission to modify tasks.

> **"Which tasks are suspended?"**

<img width="1675" alt="image" src="https://github.com/user-attachments/assets/1713bb5f-0214-4231-bb87-839ba9a0202a" />

*Live read-only task information returned by the IRIS Ops Skill.*

Task management is **read-only**: the Copilot never runs, suspends, resumes, deletes or schedules tasks, and task operations are not in the capability catalog.

Task management is **read-only**: the Copilot never runs, suspends, resumes, deletes or schedules tasks, and task operations are not in the capability catalog.

### Structured execution trace

Each Copilot change request is recorded with the existing execution-trace infrastructure (the same store, optional IRIS persistence and `GET /api/iris/observability/traces` endpoint), as two linked traces with one span per lifecycle stage:

- **`copilot.plan`** (from `/plan`, change requests only): `requested → classified → issue_detected → plan_created → confirmation_required`, or `plan_rejected` with the planner's reason.
- **`copilot.execute`** (from `/execute`): `requested → confirmation_received → authorized → issue_detected → executing → executed → verification → resolved`, or a failure stage named by its failure code.

The plan returns the plan trace's `trace_id`, the execute trace links to it, and the `executed` stage links to the executor's own operation trace. Trace IDs are informational only and never affect a decision. Trace attributes are limited to an allowlist of keys and simple values: raw user messages and secrets are never recorded (only the message length). Read-only questions create no trace, and Copilot traces do not add duplicate entries to an issue's resolution history.

### Structured failure states

`POST /api/iris/copilot/execute` returns a machine-readable `failure` code (`null` on success) alongside the broad `status` and the human-readable `detail`. The same code names the failure stage of the `copilot.execute` trace:

| Failure code | Meaning |
|---|---|
| `plan_rejected` | The plan is not for an approved capability (or, in a plan trace, the planner refused the request) |
| `authorization_failed` | Not explicitly confirmed, not authorized, the authorization does not match the plan, or IRIS requires a privilege the session lacks (such as `%Admin_Secure`) |
| `issue_not_detected` | The issue is no longer detected (or the issues could not be read) when the operation is about to run |
| `target_changed` | The plan's target is invalid, differs from the authorized target, or no longer matches the detected issue |
| `parameter_mismatch` | The submitted parameters differ from those rebuilt from the detected issue |
| `resource_protected` | The target is a protected resource (system or mirrored database, System or Command Center web application) |
| `execution_failed` | The operation did not complete successfully |
| `verification_failed` | The operation ran, but its verification did not pass |
| `issue_still_detected` | The operation was verified, but the Issue Resolver still reports the issue |

`POST /api/iris/copilot/plan` keeps its own `reason` field (for example `issue_not_detected`, `ambiguous_target` or `resource_protected`) when no plan is created.

### Safety guarantees

- **Closed, allowlisted operations.** Only the three catalog capabilities can be planned or executed; unsupported or unknown operations are refused.
- **AI output is only a proposal.** The provider returns text such as *"Mount database IPM"*. It never supplies operation parameters and cannot call IRIS.
- **Parameters come from the detected issue and the catalog.** Ambiguous, undetected or protected targets are refused.
- **Fresh checks at execution time.** The issue is re-detected by its stable issue ID, parameters are rebuilt from it, and authorization is re-checked on the server. A plan whose target or parameters were changed in the browser does not match and is refused before anything reaches IRIS.
- **Explicit confirmation before any change.** Nothing is executed without the **Confirm & Execute** button.
- **Protected resources.** IRIS system and mirrored databases, System web applications and the web applications the Command Center itself uses are never changed.
- **Verification after every change.** Success requires the handler's verification and the Copilot's own check; the attempt is recorded in the operation's trace (and, for issue-backed operations, in the issue's resolution history).
- **No arbitrary execution path.** The Copilot has no SQL, ObjectScript, shell, Python or arbitrary database access; every change goes through a registered operation handler.

### Copilot API

| Method & path | Purpose |
|---|---|
| `GET /api/iris/copilot/context` | The bounded, read-only operational context (including active issues and task details) |
| `GET /api/iris/copilot/capabilities` | The closed capability catalog with its metadata (read-only) |
| `POST /api/iris/copilot/classify` | Deterministic intent of a message |
| `POST /api/iris/copilot/ask` | Structured, read-only answer (`answer`, `observations`, `proposed_action`, `requires_confirmation`) |
| `POST /api/iris/copilot/plan` | Turns a proposal into a plan (or a `reason` why not); returns the plan's `trace_id` |
| `POST /api/iris/copilot/authorize` | Checks a plan against the caller's privileges and the confirmation rule; executes nothing |
| `POST /api/iris/copilot/execute` | Executes an authorized, confirmed plan and verifies it; returns `status`, `failure`, `detail` and `trace_id` |

### Current limitations

- `web_app.set_enabled` is covered by automated tests but has not yet been verified against a live IRIS instance.
- `journal.update_purge_archived` is a direct setting request, so when run from the Copilot it is not linked to the Issue Resolver's resolution history.
- The deterministic provider understands specific phrasings (see each capability's example requests).
- Task management is read-only, and task summaries cover at most the 10 tasks included in the context.
- Execution traces are kept in memory (newest 200) unless `PERSIST_TRACES_TO_IRIS` is enabled.

➡️ **Demo walkthrough:** [docs/ops-skill-demo.md](docs/ops-skill-demo.md)

---

# 📦 Installation

## Prerequisites

- Docker Desktop / Docker Engine
- Docker Compose
- Git

## Docker 

### 1. Clone

```bash
git clone https://github.com/mwaseem75/iris-command-center.git
cd iris-command-center
```

### 2. Configure environment

Copy the example file:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Edit `.env` with the credentials for the IRIS environment used by the Docker stack.

> **Do not commit `.env`.** It is intentionally excluded from the Docker build context.

### 3. Builds & starts

```bash
docker compose up -d --build
```

Check the services:

```bash
docker compose ps
```

### 4. Open Command Center

```text
http://localhost:52773/iris-command-center/index.html
```

## Installation with ZPM

```text
zpm "install iris-command-center"
```

### Endpoints

| URL | Purpose |
|---|---|
| `http://localhost:52773/iris-command-center/index.html` | Command Center |
| `http://localhost:8000/docs` | FastAPI OpenAPI documentation |
| `http://localhost:52773/csp/sys/UtilHome.csp` | IRIS Management Portal |


---

# 🎯 Getting Started

IRIS Command Center is designed around practical operational scenarios rather than isolated screens.

## Core Features

### 📊 Dashboard & Explorers
The dashboard provides a live operational snapshot. 
<img width="2172"  alt="image" src="https://github.com/user-attachments/assets/ca0ac865-94f7-46f1-99f5-712364961983" />

### 🩺 Health Center
Health Center presents an overall health status and assessment coverage across **Performance, Tasks, Databases, Security, Web Applications, and System**. It shows findings, evidence, and recommendations from available read-only checks, reusing Issue Resolver detections where applicable rather than duplicating them.
<img width="2207" alt="image" src="https://github.com/user-attachments/assets/9202195a-e8e8-44aa-80e9-2202d56e8c18" />

**Current Activity** displays observed values from the live IRIS Monitor Dashboard and process list, including Global References/sec, Cache Efficiency, process and session counts, and System Monitor process state. The **Performance Snapshot** distinguishes the reported current rate and efficiency from cumulative counters since IRIS startup, such as Global References, Disk Reads/Writes, and Logical Requests; cumulative values are not presented as rates.

Health Center does not apply arbitrary performance thresholds. When available data does not support a defensible assessment, the category remains **Not Assessed** while available values can still be shown for information.

### 🩺 Issue Resolver
Issue Resolver provides deterministic detection, investigation, and guided resolution for supported IRIS operational issues.
It uses live IRIS evidence to identify conditions and clearly separates issues that Command Center can safely resolve from conditions that require investigation.
Current built-in checks include:
- **Dismounted Database** — detects a database reported as dismounted and resolves it through the existing `database.mount` operation.
- **Enabled Web Application with Missing Namespace** — detects an enabled web application whose configured namespace no longer exists and safely disables the affected application through `web_app.set_enabled`.
- **Archived Journal Files Not Purged** — detects when archived journal purging is disabled and enables it through `journal.update_purge_archived`.
- **System Monitor Not Running** — detects when the IRIS System Monitor is stopped and directs the operator to investigate in System.
- **Task Manager Not Running** — detects when the IRIS Task Manager is not running and directs the operator to investigate in Tasks.
- **Database Full** — detects databases reported as full and directs the operator to investigate in Databases.
Users can also create **Custom Issue Rules** using a controlled set of live IRIS metrics. Custom rules are detection-only and can direct the operator to the relevant investigation page; they cannot execute arbitrary code or define their own remediation.
Each issue provides the available live evidence, explanation, severity, affected resource, and either a safe resolution path or an investigation path. For resolvable issues, the workflow follows the existing safety model: authorization → dry run → review → explicit confirmation → execution → verification. The resulting operation is captured in Observability and can be associated with the issue that initiated the resolution.
The issue catalog is intentionally curated: Command Center only offers deterministic resolution where a supported operation has been explicitly registered and verified. Detection-only conditions remain read-only and are never automatically modified.

**Issue Resolver — main view**
  
<img width="2178"  alt="image" src="https://github.com/user-attachments/assets/990e8f35-ac01-4229-93d4-bfce217d0e95" />

**Issue Resolver — issue details**

<img width="1274"  alt="image" src="https://github.com/user-attachments/assets/017dfb32-7b92-4ee7-88c4-60fd8cbf869a" />


### 🛠️ IRIS System Administration (Operations)
Monitor an IRIS instance, explore its configuration, and perform supported administrative tasks from one operational console.
<img width="2191"  alt="image" src="https://github.com/user-attachments/assets/d7d8a782-9cc7-47b4-a12c-80655eb40030" />

#### Demo Activity
Demo Activity provides a controlled way to demonstrate IRIS Command Center's operational workflows without relying on simulated data.
The rehearsal uses the real connected IRIS instance and performs a small set of safe, reversible actions, verifying each step and restoring the original state afterward. The workflow also produces execution traces that can be inspected in Observability.
For Issue Resolver demonstrations, Command Center can intentionally create a clearly labelled, reversible demo issue on the IPM database. The normal Issue Resolver then detects the real IRIS condition, presents the evidence and recommended solution, resolves it through the same authorization and confirmation pipeline used for normal operations, and verifies the result.
Demo Activity is separate from the Supported Actions catalog: it exists specifically for demonstrations and testing of the Command Center's safety, verification, restoration, and observability workflows.
<img width="2152"  alt="image" src="https://github.com/user-attachments/assets/3dc99495-4c6f-4d6b-ac1e-2210e822abed" />

### 👁️ Observability
Observability gives administrators a clear view of what happened inside Command Center and what IRIS recorded during those activities.
Execution Traces capture Command Center operations from request through authorization, confirmation, execution, and verification. Each trace includes timestamps, duration, status, operation details, and structured execution events. Issue Resolution workflows are linked to their originating issue, providing an evidence chain from detection → resolution → verification → execution trace. Copilot change requests add linked `copilot.plan` and `copilot.execute` traces to the same view (see [IRIS Ops Skill](#-iris-ops-skill--issue-aware-copilot)).
<img width="2183" alt="image" src="https://github.com/user-attachments/assets/131b5172-4491-4303-9907-a258dda623e8" />

### 🚨 Investigation
Investigation provides two complementary views of native IRIS operational evidence.

**Audit Investigation** provides a dedicated view of the native IRIS security audit trail. Administrators can investigate real audit events using filters such as date range, event type, event, username, namespace, and free-text search. Events can be explored in a timeline and detailed workspace, with related Command Center traces surfaced when they occur within the relevant time window. Audit results are paginated for focused investigation.
<img width="2207" alt="image" src="https://github.com/user-attachments/assets/63d0621e-e51b-4851-b559-c8512e0ae5fa" />

**Message Log** provides a read-only view of the native IRIS `messages.log`. Administrators can search messages, filter by severity level, browse paginated results, and open individual entries for their full metadata and message content. The log is read directly from IRIS using a fixed read-only path and is never modified by Command Center.
<img width="2196" alt="image" src="https://github.com/user-attachments/assets/04649d90-fb72-4ad6-9fa1-4a3b5fba242f" />

Together, these views answer two complementary operational questions:

- **Execution Traces:** What did Command Center do?
- **Audit Investigation:** What did IRIS record as a security/audit event?
- **Message Log:** What messages and diagnostic information did IRIS report?

This separation provides a focused operational view of Command Center activity alongside the underlying IRIS audit and message evidence.

### 🤖 AI-Assisted 
Ask natural-language questions about live IRIS data while keeping the assistant inside the same controlled application API boundary.
Requests are classified deterministically on the backend, and answers come from the Copilot's local deterministic provider.
The assistant is issue-aware and can carry out supported, catalog-backed changes — but only as a backend-generated proposal that the user explicitly confirms, and only through the same authorization, execution and verification framework as the rest of the application. See [IRIS Ops Skill — Issue-aware Copilot](#-iris-ops-skill--issue-aware-copilot).
Knowledge questions may use IRIS Vector Search for supporting context; search results never trigger administrative changes.
<img width="2175"  alt="image" src="https://github.com/user-attachments/assets/52a5785f-321d-4451-bb6c-00067b6e7869" />

### 🌐 Web Application 
Inspect web application configuration, authentication, CORS, JWT, sessions, cookies, REST endpoints, and related application state. Explore generated REST API definitions when developing, integrating with, documenting, or troubleshooting an IRIS REST application.
<img width="2175"  alt="image" src="https://github.com/user-attachments/assets/6157798b-b62e-4f3b-91e3-974b66381898" />
#### REST Applications Endpoints
REST Applications provide an interactive view of the REST APIs exposed by IRIS web applications. Double-click a REST-enabled application to explore its available endpoints, HTTP methods, paths, and API details directly from the Command Center.
This provides a convenient way to inspect the REST surface of an IRIS instance without navigating separately through the Management Portal, making it easier to understand and investigate deployed REST services.
<img width="1608"  alt="image" src="https://github.com/user-attachments/assets/5795c39a-1c61-4eb6-ba48-efdc15bdb57b" />


### 🔐 Security Review
Review users, roles, resources, authentication posture, wallet metadata, X.509 metadata, and OAuth2 configuration while keeping secrets out of the browser.
Security is organized into focused areas rather than exposing sensitive configuration indiscriminately.

| Area | Visibility |
|---|---|
| **Identity & Access** | Users, roles, resources, access relationships |
| **Authentication** | Services, web authentication, superservers, class access |
| **Wallet** | Collections, resources, secret names and types |
| **X.509** | Credential and certificate metadata without private keys |
| **OAuth2** | Server/client configuration metadata without secrets or tokens |
<img width="2172" alt="image" src="https://github.com/user-attachments/assets/54083e46-6aee-4d3c-86a7-74de644cd462" />
Sensitive information is protected. The application deliberately withholds or filters values such as:
- Passwords
- JWTs
- Authorization headers
- Private keys
- Wallet secret values
- OAuth secrets/tokens
- Session identifiers
- Sensitive personal fields

### 🗓️ Tasks
Tasks provides a live view of scheduled IRIS tasks, including their current state, configuration, upcoming runs, schedules, and most recent run information. Administrators can search and filter tasks, open a detailed view, and inspect task settings while sensitive configuration values are automatically redacted.

The Tasks page provides four complementary views:

- **All Tasks** — search and filter the complete live task list.
- **Upcoming** — view the next scheduled runs reported by IRIS, ordered by time and grouped by date.
- **Schedule** — inspect the configured schedule for each task, including period, time of day, date range, and next run.
- **Last Runs** — review the most recent run information reported for each task. This is intentionally not presented as a full execution history.

For eligible user tasks, Command Center also provides a controlled **Run Now** operation with authorization, explicit confirmation, and post-execution verification. System tasks are protected from manual execution.

Task execution follows the same authorization → confirmation → execution → verification workflow used by other administrative operations.

<img width="2172" alt="image" src="https://github.com/user-attachments/assets/d98404e0-cbff-44a8-865a-5a83c26fe0fc" />

**Upcoming**

<img width="2172"  alt="image" src="https://github.com/user-attachments/assets/24557671-d213-484a-af3b-a9fd81777ae3" />


**Schedule**

<img width="2161"  alt="image" src="https://github.com/user-attachments/assets/b1419160-fed6-476f-9d83-2877e7511e76" />


**Last Runs**

<img width="2156"  alt="image" src="https://github.com/user-attachments/assets/0902e9e8-9cbb-4efc-a0ed-379c27a386ac" />


### 📖 Journal
Journal provides a live view of IRIS journal configuration, allowing administrators to inspect key journal settings and understand the current journaling posture of the connected instance.
Command Center also supports controlled updates to selected journal settings through the same authorization → confirmation → execution → verification workflow used by other administrative operations.
Changes are validated before execution and verified against the live IRIS configuration afterward, with the operation captured in Observability for traceability.
<img width="2167"  alt="image" src="https://github.com/user-attachments/assets/07784520-ae0e-4515-9db4-f54faec03317" />


---
## Advanced Capabilities

### 🩺 Deterministic Issue Resolver

The **Issue Resolver** provides a controlled operational path from detecting an IRIS condition to either a safe resolution or guided investigation: **Detect → Explain → Recommend → Safely Resolve → Verify**. Detection and recommendations are deterministic: they come from live IRIS data and the Issue Resolution Catalog, not from an AI model. Stable issue IDs identify findings by issue type and canonical resource, while resolution readiness indicates whether an issue is ready for a resolution check, blocked, requires investigation, or has insufficient evidence.
<img width="2068" alt="image" src="https://github.com/user-attachments/assets/4db1e9a5-3d80-48af-b2a8-666ac8176570" />

The resolver separates issues into two categories:

- **Resolvable issues** — Command Center has a deterministic detection rule and a registered, authorized, verified operation that can safely resolve the condition.
- **Detection-only issues** — Command Center can reliably detect and explain the condition, but does not have a supported remediation operation. The operator is directed to the appropriate investigation area instead.

The current built-in issue catalog includes:

#### `database_dismounted` — Dismounted Database

- **Detection:** live IRIS database information reports the database as dismounted.
- **Impact:** namespaces that depend on the database for Globals or Routines are identified from live namespace information.
- **Recommendation:** the catalog-defined solution is `database.mount`, subject to the required IRIS **Operate** privilege and safety checks.
- **Resolution:** the existing database mount workflow performs authorization, dry-run, review, explicit confirmation, execution, and verification.
- **Verification:** the database is read back from IRIS and the issue detector confirms that the issue is gone.
- **Observe:** the resolution is recorded as an execution trace and associated with the issue that initiated the resolution.

#### `web_app_namespace_missing` — Enabled Web Application with Missing Namespace

- **Detection:** an enabled web application references a namespace that is not present in the live namespace list.
- **Impact:** the affected web application and its missing namespace relationship are shown as evidence.
- **Recommendation:** the catalog-defined solution is `web_app.set_enabled` with `Enabled=false`.
- **Resolution:** the affected application is safely disabled through the normal authorization, confirmation, execution, and verification workflow. Command Center does not attempt to recreate the missing namespace.
- **Verification:** the web application state is read back and the issue detector confirms that the condition is no longer active.
- **Observe:** the resolution is captured in Observability with the issue context.

#### `journal_purge_archived_off` — Archived Journal Files Not Purged

- **Detection:** live journal configuration shows an archive location while archived journal purging is disabled.
- **Recommendation:** the catalog-defined solution is `journal.update_purge_archived` with `PurgeArchived=true`.
- **Resolution:** the setting is changed only through the existing authorized journal workflow with confirmation and verification.
- **Observe:** the controlled operation is captured in Observability with the issue context.

### Detection-only checks

The catalog also includes conditions where Command Center intentionally provides detection and investigation rather than remediation:

- `system_monitor_not_running` — detects when the IRIS System Monitor is not running and directs the operator to **System**.
- `task_manager_not_running` — detects when the IRIS Task Manager is not running and directs the operator to **Tasks**.
- `database_full` — detects databases reported as full and directs the operator to **Databases**.
- `audit_logging_disabled` — detects when IRIS reports auditing disabled and directs the operator to review audit policy on **Security**; it does not enable auditing automatically.

These checks remain read-only. Command Center does not invent a remediation operation simply because an issue has been detected.

Related findings are linked through deterministic rules based on shared resources or documented operational relationships. The Issue Resolver drawer shows issue identity, resource, readiness, and backend-provided related findings. It also presents issue-level Resolution History projected from existing execution traces, including lifecycle evidence where available: **BEFORE → ACTION → RESULT → AFTER → VERIFICATION**.

### Custom Issue Rules

Administrators can also define **Custom Issue Rules** using a controlled set of live IRIS metrics and comparison operators.

Custom rules can identify conditions such as unusually high process counts or application errors and direct the operator to the appropriate investigation area. They are intentionally **detection-only**: users cannot provide arbitrary code, expressions, API calls, or remediation logic.

When enabled, custom rules can be persisted in IRIS using:

```text
^CommandCenterIssueRule("rule", <name>)
```

### 💾 Persisting traces in IRIS
Command Center can persist its execution traces **inside the connected InterSystems IRIS instance**.
This makes observability more than a browser-only feature.
<img width="1753"  alt="image" src="https://github.com/user-attachments/assets/02c0089a-2f1d-4ade-8b19-c39682775e3a" />
<img width="1749" alt="image" src="https://github.com/user-attachments/assets/154dfd30-10f5-40d9-8dc7-bf1a2c1b9a91" />
Execution traces can optionally be persisted directly in the connected IRIS instance. This allows operational history to survive Command Center restarts rather than existing only in application memory.
When trace persistence is enabled, Command Center stores each completed execution trace in the IRIS `USER` namespace using the native IRIS API:
<img width="2508"  alt="image" src="https://github.com/user-attachments/assets/21b0023f-a73d-41f9-8ea5-67483248154d" />


---

### 🔍 IRIS Vector Search

Command Center demonstrates **InterSystems IRIS Vector Search** as an operational knowledge capability.
Vector Search provides supporting operational knowledge only; it does not detect issues, select mutations, or execute remediation.

<img width="1754"  alt="image" src="https://github.com/user-attachments/assets/0d1df68b-6c57-4185-9d23-adfe1f765fc4" />
Operational knowledge chunks and their generated embedding vectors stored directly in an IRIS SQL table.
<img width="2508"  alt="image" src="https://github.com/user-attachments/assets/285029f5-6ea1-482d-8f3a-6b78b57ac68b" />

---

### 🎯 Demo Activity
Command Center includes a controlled **Demo Activity** workflow for demonstrating the safety model without leaving arbitrary configuration behind.
Alongside the standard rehearsal, Demo Activity offers **Create Demo Issue**: after explicit confirmation it intentionally creates a real, reversible issue (IPM is temporarily dismounted), which is then detected, resolved and verified through the normal Issue Resolver workflow, and the environment is restored afterward.
<img width="1765" alt="image" src="https://github.com/user-attachments/assets/af2f6967-0f3d-40db-bf30-e17b686dc23d" />

---
### 🧪 Testing & Verification

<img width="1749"  alt="image" src="https://github.com/user-attachments/assets/87883946-9eca-4eb6-9db3-5693854c4357" />
The project uses automated tests plus live IRIS verification to validate both the application logic and its behavior against a real InterSystems IRIS instance.
The test suite covers:

- **API and business logic** — issue detection, resolution catalogs, operation validation, authorization, and safety restrictions.
- **Resolution workflows** — dry-run behavior, explicit confirmation, execution, post-action verification, and failure/restore paths.
- **Security controls** — required IRIS privileges, protected resources, rejected operations, and prevention of unauthorized changes.
- **Observability** — execution traces, resolution context, trace persistence, and hydration after application restart.
- **Issue Resolver** — deterministic detection, evidence, affected-resource information, resolution parameters, and verification.
- **Frontend smoke tests** — navigation, Issue Resolver flows, resource-specific resolution paths, and critical UI behavior.
- **Live IRIS verification** — selected workflows are exercised against a real IRIS 2026.2 instance to confirm that API responses, privileges, operations, and resulting system state match expectations.

The test suite is designed to verify not only that an operation succeeds, but also that **unsafe or invalid operations are refused and that successful changes are verified against the resulting IRIS state**.
Current backend test status: **1,289 automated tests — 1,280 passing, 9 known failures**. The 9 failures are pre-existing and were not introduced by the Phase 3.5 IRIS Ops Skill work (capability catalog, capability metadata, task catalog, execution trace and failure states): 4 are in earlier Copilot tests (test setup with an incomplete IRIS mock, and outdated expectations), and 5 are in Issue Catalog, Health Center and database-mount tests whose expectations predate later changes. The IRIS Ops Skill tests cover the capability catalog, planning, execution, task answers, traces and every structured failure code. Frontend smoke tests cover the critical browser workflows.

# ⚙️ Configuration

The Docker deployment supports these environment variables:

| Variable | Purpose |
|---|---|
| `IRIS_BASE_URL` | IRIS web/API base URL |
| `IRIS_USERNAME` | IRIS service account username |
| `IRIS_PASSWORD` | IRIS service account password |
| `IRIS_NAMESPACE` | IRIS namespace used for native operations |
| `IRIS_SUPERSERVER_PORT` | IRIS Native API / Superserver port |
| `PERSIST_TRACES_TO_IRIS` | Persist execution traces inside IRIS |
| `ENABLE_KNOWLEDGE_SEARCH` | Enable IRIS Vector Search knowledge |
| `AUTO_RUN_DEMO_ACTIVITY` | Enable the optional startup demo rehearsal |

---







