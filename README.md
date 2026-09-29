# ✨ IRIS Command Center

**Observe. Investigate. Act—safely.**

A modern operational console for **InterSystems IRIS** that brings monitoring, administration, investigation, security, visibility, issue resolution, and operational tracing into one place.
It combines live IRIS system information with controlled administrative workflows, native audit investigation, structured execution traces, security visibility, and a deterministic AI Assistant.
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
# 🧭 Features at a Glance

| Area | What you can do |
|---|---|
| 📊 **Dashboard** | View live system state, databases, processes, web apps, tasks, resources, alerts, Issues & Recommendations, and recent activity |
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
| 🤖 **AI Assistant** | Ask natural-language questions backed by live Command Center APIs |
| 🔍 **Vector Search** | Search an IRIS-persisted operational knowledge corpus using IRIS Vector Search |
| 🐍 **Embedded Python** | Inspect live diagnostics from IRIS Embedded Python |
| 🎬 **Demo Activity** | Demonstrate controlled operations and an intentional, reversible demo issue, with verification, restoration, and execution tracing |

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
Execution Traces capture Command Center operations from request through authorization, confirmation, execution, and verification. Each trace includes timestamps, duration, status, operation details, and structured execution events. Issue Resolution workflows are linked to their originating issue, providing an evidence chain from detection → resolution → verification → execution trace.
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
The current AI Assistant intentionally uses a **deterministic intent classifier**, not an external LLM.
It provides a natural-language interface while keeping the operational path inside the existing application architecture.
Knowledge questions may use IRIS Vector Search for supporting context; search results never trigger administrative changes, and any change the assistant can request goes through the same authorization, confirmation and verification framework as the rest of the application.
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

The **Issue Resolver** provides a controlled operational path from detecting an IRIS condition to either a safe resolution or guided investigation. Detection and recommendations are deterministic: they come from live IRIS data and the Issue Resolution Catalog, not from an AI model.
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

These checks remain read-only. Command Center does not invent a remediation operation simply because an issue has been detected.

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
At the time of the current release, the backend test suite contains **802 automated tests**, with frontend smoke tests covering the critical browser workflows.

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










