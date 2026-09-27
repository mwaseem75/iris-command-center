# ✨ IRIS Command Center

**Observe. Investigate. Act—safely.**

A modern operational console for **InterSystems IRIS** that brings monitoring, administration, investigation, security visibility, issue resolution, and operational tracing into one place.
It combines live IRIS system information with controlled administrative workflows, native audit investigation, structured execution traces, security visibility, and a deterministic AI Assistant.
<p align="center">
  <img width="2507" height="1278" alt="image" src="https://github.com/user-attachments/assets/11287960-6cfe-4402-9429-6a2af1a55e96" />

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
| 🗂️ **Namespaces** | Explore namespaces, relationships, and create namespaces safely |
| 💾 **Databases** | Inspect databases, storage, integrity, and perform controlled create, mount, and dismount workflows |
| ⚙️ **Processes** | Search, filter, and investigate live IRIS processes |
| 🌐 **Web Applications** | Inspect configuration, REST applications, sessions, enable/disable apps, and update descriptions |
| 🔍 **REST API Explorer** | Explore generated REST API definitions, endpoints, methods, parameters, and implementation details |
| ⏱️ **Tasks** | Inspect task state, schedules, settings, execution information, and supported Run Now workflows |
| 🔐 **Security** | Explore users, roles, resources, authentication posture, wallets, X.509, and OAuth2 |
| 🔌 **Extensions & Integrations** | Inspect external language servers, filesystem access purposes, and wallet integration metadata |
| 🔎 **Investigation** | Search the native IRIS security audit trail and relate activity to Command Center traces |
| 👁️ **Observability** | Inspect structured execution traces and optionally persist them inside IRIS |
| 🩺 **Issue Resolver** | Detect supported issues from live evidence, see their impact, resolve them safely through the existing operations, verify the result, and follow the execution trace |
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
<img width="2172" height="1168" alt="image" src="https://github.com/user-attachments/assets/ca0ac865-94f7-46f1-99f5-712364961983" />

### 🩺 Issue Resolver
Issue Resolver provides deterministic detection and guided resolution for supported IRIS operational issues.
The resolver currently detects:
Dismounted Database — detects a database reported as dismounted and resolves it through the existing database.mount operation.
Enabled Web Application with Missing Namespace — detects an enabled web application whose configured namespace no longer exists and resolves it by safely disabling the affected application through the existing web_app.set_enabled operation.
Each issue is based on live IRIS API evidence rather than simulated data. The resolver presents the affected resource, evidence, explanation, recommended solution, required privilege, risk level, and resolution workflow.
Resolution always follows the same controlled lifecycle: authorization → explicit confirmation → execution → verification. The resulting operation is captured in Observability and can be associated with the issue that initiated the resolution.
The issue catalog is intentionally curated: Command Center reports conditions where it has a deterministic detection rule and a safe, verified resolution path.
<img width="2172" height="1085" alt="image" src="https://github.com/user-attachments/assets/e3ce708b-1e69-4d08-b7ae-b187c1adeded" />

### 🛠️ IRIS System Administration (Operations)
Monitor an IRIS instance, explore its configuration, and perform supported administrative tasks from one operational console.
<img width="2191"  alt="image" src="https://github.com/user-attachments/assets/d7d8a782-9cc7-47b4-a12c-80655eb40030" />

#### Demo Activity
Demo Activity provides a controlled way to demonstrate IRIS Command Center's operational workflows without relying on simulated data.
The rehearsal uses the real connected IRIS instance and performs a small set of safe, reversible actions, verifying each step and restoring the original state afterward. The workflow also produces execution traces that can be inspected in Observability.
For Issue Resolver demonstrations, Command Center can intentionally create a clearly labelled, reversible demo issue on the IPM database. The normal Issue Resolver then detects the real IRIS condition, presents the evidence and recommended solution, resolves it through the same authorization and confirmation pipeline used for normal operations, and verifies the result.
Demo Activity is separate from the Supported Actions catalog: it exists specifically for demonstrations and testing of the Command Center's safety, verification, restoration, and observability workflows.
<img width="2152" height="1137" alt="image" src="https://github.com/user-attachments/assets/3dc99495-4c6f-4d6b-ac1e-2210e822abed" />

### 👁️ Observability
Observability gives administrators a clear view of what happened inside Command Center and what IRIS recorded during those activities.
Execution Traces capture Command Center operations from request through authorization, confirmation, execution, and verification. Each trace includes timestamps, duration, status, operation details, and structured execution events. Issue Resolution workflows are linked to their originating issue, providing an evidence chain from detection → resolution → verification → execution trace.
<img width="2183" alt="image" src="https://github.com/user-attachments/assets/131b5172-4491-4303-9907-a258dda623e8" />

### 🚨 Investigation
Audit Investigation provides a dedicated view of the native IRIS security audit trail. Administrators can investigate real audit events using filters such as date range, event type, event, username, namespace, and free-text search. Events can be explored in a timeline and detailed workspace, with related Command Center traces surfaced when they occur within the relevant time window.
Together, these views answer two complementary questions:
Execution Traces: What did Command Center do?
Audit Investigation: What did IRIS record?
This separation provides an operational view of Command Center activity alongside the underlying IRIS audit evidence.
<img width="2177"  alt="image" src="https://github.com/user-attachments/assets/88b48323-fba2-4eed-ad3d-ef086f6206a4" />

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
<img width="1608" height="1127" alt="image" src="https://github.com/user-attachments/assets/5795c39a-1c61-4eb6-ba48-efdc15bdb57b" />


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
Tasks provides a live view of scheduled IRIS tasks, including their current state and configuration. Administrators can search and filter tasks, open a detailed view, and inspect task settings while sensitive configuration values are automatically redacted.
For eligible user tasks, Command Center also provides a controlled Run Now operation with authorization, explicit confirmation, and post-execution verification. System tasks are protected from manual execution.
Task execution follows the same authorization → confirmation → execution → verification workflow used by other administrative operations.
<img width="2175" height="1237" alt="image" src="https://github.com/user-attachments/assets/3a929158-9c59-4123-aafa-e8c33456fe38" />

### 📖 Journal
Journal provides a live view of IRIS journal configuration, allowing administrators to inspect key journal settings and understand the current journaling posture of the connected instance.
Command Center also supports controlled updates to selected journal settings through the same authorization → confirmation → execution → verification workflow used by other administrative operations.
Changes are validated before execution and verified against the live IRIS configuration afterward, with the operation captured in Observability for traceability.
<img width="2167" height="1127" alt="image" src="https://github.com/user-attachments/assets/07784520-ae0e-4515-9db4-f54faec03317" />


---
## Advanced Capabilities

### 🩺 Deterministic Issue Resolver
The **Issue Resolver** provides a controlled operational path from a detected issue to a verified resolution. Detection and recommendations are deterministic: they come from live IRIS data and the Issue Resolution Catalog, not from an AI model.
<img width="1827" height="637" alt="image" src="https://github.com/user-attachments/assets/9b2de03f-cda5-4e54-b073-3a24eca312b2" />
The resolver currently supports two curated issue types:
#### `database_dismounted` — Dismounted Database
- **Detection:** live evidence from IRIS (`GET /v2/databases`, `GET /v2/database-dirs`) shows the database reported as `Dismounted`.
- **Impact:** the namespaces that use the database for **Globals** or **Routines** are identified using `GET /v2/namespaces`.
- **Recommendation:** the catalog-defined solution is to mount the database read-write with **`database.mount`**, with the required **Operate** privilege and its defined risk level.
- **Resolve:** the operation runs through the normal **authorization → explicit confirmation → execution** path. There is no bypass.
- **Verification:** the operation verifies that the database is mounted, and issue detection confirms that the issue is gone.
- **Observe:** the resolution is recorded as an execution trace, labelled with the issue it resolved, and can be opened in Observability.

#### `web_app_namespace_missing` — Enabled Web Application with Missing Namespace
- **Detection:** live IRIS data compares enabled web applications from `GET /v2/web-apps` with the namespaces returned by `GET /v2/namespaces`. An issue is reported when an enabled web application references a namespace that does not exist.
- **Impact:** the affected web application, its configured namespace, and enabled state are shown as live evidence.
- **Recommendation:** the catalog-defined solution is to disable the affected web application with **`web_app.set_enabled`**. This prevents a broken endpoint from remaining enabled; it does not recreate the missing namespace.
- **Resolve:** the operation follows the same **authorization → explicit confirmation → execution** workflow and uses the existing web application safety restrictions.
- **Verification:** the web application is re-read and issue detection confirms that the missing-namespace condition is no longer reported.
- **Observe:** the resolution is recorded as an execution trace and associated with the issue that initiated the resolution.

#### Evidence-driven Resolution
Every resolution is backed by a chain of real evidence:
```text
Detection Evidence → Impact Evidence → Resolution Operation → Verification Evidence → Execution Trace

### 💾 Persisting traces in IRIS
Command Center can persist its execution traces **inside the connected InterSystems IRIS instance**.
This makes observability more than a browser-only feature.
<img width="1753"  alt="image" src="https://github.com/user-attachments/assets/02c0089a-2f1d-4ade-8b19-c39682775e3a" />
<img width="1749" alt="image" src="https://github.com/user-attachments/assets/154dfd30-10f5-40d9-8dc7-bf1a2c1b9a91" />
```
---

### 🔍 IRIS Vector Search

Command Center demonstrates **InterSystems IRIS Vector Search** as an operational knowledge capability.
Vector Search provides supporting operational knowledge only; it does not detect issues, select mutations, or execute remediation.

<img width="1754"  alt="image" src="https://github.com/user-attachments/assets/0d1df68b-6c57-4185-9d23-adfe1f765fc4" />

---

### 🎯 Demo Activity
Command Center includes a controlled **Demo Activity** workflow for demonstrating the safety model without leaving arbitrary configuration behind.
Alongside the standard rehearsal, Demo Activity offers **Create Demo Issue**: after explicit confirmation it intentionally creates a real, reversible issue (IPM is temporarily dismounted), which is then detected, resolved and verified through the normal Issue Resolver workflow, and the environment is restored afterward.
<img width="1765" alt="image" src="https://github.com/user-attachments/assets/af2f6967-0f3d-40db-bf30-e17b686dc23d" />

---
### 🧪 Testing & Verification
The project uses automated tests plus live IRIS verification.
<img width="1749"  alt="image" src="https://github.com/user-attachments/assets/87883946-9eca-4eb6-9db3-5693854c4357" />


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










