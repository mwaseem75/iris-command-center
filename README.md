# ✨ IRIS Command Center

**Observe. Investigate. Act—safely.**

A modern operational console for **InterSystems IRIS** that brings monitoring, administration, investigation, security visibility, issue resolution, and operational tracing into one place.
It combines live IRIS system information with controlled administrative workflows, native audit investigation, structured execution traces, security visibility, and a deterministic AI Assistant.
<p align="center">
  <img src="https://github.com/user-attachments/assets/dd29861d-7f46-454e-ab0a-6aca372e2f7e" alt="IRIS Command Center" width="720">
</p>
<p align="center">
  <a href="https://www.intersystems.com/"><img src="https://img.shields.io/badge/Platform-InterSystems%20IRIS-009688?style=flat-square" alt="InterSystems IRIS"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/Backend-FastAPI-009688?style=flat-square" alt="FastAPI"></a>
  <a href="https://developer.mozilla.org/en-US/docs/Web/JavaScript"><img src="https://img.shields.io/badge/Frontend-Vanilla%20JavaScript-F7DF1E?style=flat-square" alt="Vanilla JavaScript"></a>
  <a href="https://www.docker.com/"><img src="https://img.shields.io/badge/Deployment-Docker-2496ED?style=flat-square" alt="Docker"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Language-Python-3776AB?style=flat-square" alt="Python"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="MIT"></a>
</p>

---
## 🎬 Application Layout
<img width="2500" alt="image" src="https://github.com/user-attachments/assets/ee5c61bd-3f14-4c5f-bca6-29d27685790e" />

---

## 🏗️ Architecture

<img width="1536" alt="image" src="https://github.com/user-attachments/assets/e43f7850-f6a0-4eff-a792-bb9a70dc4f9e" />

---

## ⭐ Why It Is Different

IRIS Command Center is not simply another dashboard.

Its administrative workflows follow a consistent safety model:

```text
Request
   ↓
Authorize
   ↓
Dry Run
   ↓
Review
   ↓
Confirm
   ↓
Execute
   ↓
Verify
   ↓
Trace
```

That same model is reused across supported mutations.

### Design principles

- **Live IRIS data** — no fabricated system health or performance values.
- **Privilege-aware operations** — required IRIS privileges are evaluated by the backend.
- **Dry-run first** — supported mutations can be previewed without changing IRIS.
- **Explicit confirmation** — mutations require deliberate user confirmation.
- **Post-action verification** — the final state is read back from IRIS.
- **Traceable operations** — controlled actions produce structured execution traces.
- **Secret filtering** — sensitive values are removed before reaching the browser or traces.
- **Controlled AI** — the assistant does not receive a privileged shortcut into IRIS.

---

# 🎯 Use Cases

IRIS Command Center is designed around practical operational scenarios rather than isolated screens.

### 1. 🛠️ IRIS System Administration

Monitor an IRIS instance, explore its configuration, and perform supported administrative tasks from one operational console.

### 2. 🚨 Incident Investigation

Start with an observed issue, inspect system state and configuration, investigate native IRIS audit activity, and follow related Command Center execution traces.

### 3. 🛡️ Safe Configuration Changes

Preview a supported change, review what will happen, explicitly confirm it, execute it against IRIS, and verify the resulting state.

Examples include:

- Creating a namespace
- Creating a database
- Mounting or safely dismounting a database
- Updating journal configuration
- Enabling or disabling a web application
- Updating a web application description
- Managing supported user state
- Running an eligible task

### 4. 🌐 Web Application Troubleshooting

Inspect web application configuration, authentication, CORS, JWT, sessions, cookies, REST endpoints, and related application state.

### 5. 🔐 Security Review

Review users, roles, resources, authentication posture, wallet metadata, X.509 metadata, and OAuth2 configuration while keeping secrets out of the browser.

### 6. 🩺 Database Troubleshooting & Recovery

Detect supported database-state issues, understand the evidence behind the recommended fix, execute the existing safe operation, and verify that the issue is resolved.

### 7. 🔍 REST API Discovery

Explore generated REST API definitions when developing, integrating with, documenting, or troubleshooting an IRIS REST application.

### 8. 🤖 AI-Assisted IRIS Operations

Ask natural-language questions about live IRIS data while keeping the assistant inside the same controlled application API boundary.

### 9. 👁️ Operational Audit & Traceability

Understand two complementary perspectives:

```text
IRIS Native Audit
      ↓
What security activity did IRIS record?

Command Center Trace
      ↓
What operation did Command Center perform?
```

### 10. 💻 IRIS Developer & Community Reference

Use the project as a reference for:

- IRIS SysAdmin API integration
- Privilege-aware operations
- Safe mutation workflows
- Post-action verification
- REST API discovery
- Security-aware API response filtering
- Operational observability
- IRIS Vector Search
- Embedded Python
- Controlled AI assistance

### 11. 🐳 DevOps & Containerized Environments

Start a reproducible IRIS + Command Center environment with Docker. The frontend is automatically installed into IRIS and served by IRIS after startup.

### 12. 🎬 Demonstration & Training

Use Demo Activity and Issue Resolution Rehearsal to demonstrate the complete operational lifecycle:

```text
Detect
  ↓
Explain
  ↓
Recommend
  ↓
Review
  ↓
Confirm
  ↓
Execute
  ↓
Verify
  ↓
Trace
```

---

# 🧭 Features at a Glance

| Area | What you can do |
|---|---|
| 📊 **Dashboard** | View live system state, databases, processes, web apps, tasks, resources, and recent activity |
| 🗂️ **Namespaces** | Explore namespaces, relationships, and create namespaces safely |
| 💾 **Databases** | Inspect databases, storage, integrity, create/mount/dismount with controlled workflows |
| ⚙️ **Processes** | Search, filter, and investigate live IRIS processes |
| 🌐 **Web Applications** | Inspect configuration, REST applications, sessions, enable/disable apps, update descriptions |
| ⏱️ **Tasks** | Inspect task state, schedules, settings, and supported Run Now workflow |
| 🔐 **Security** | Explore users, roles, resources, authentication posture, wallets, X.509, and OAuth2 |
| 🔎 **Investigation** | Search the native IRIS security audit trail and relate activity to Command Center traces |
| 👁️ **Observability** | Inspect structured execution traces and persist them inside IRIS |
| 🩺 **Issue Resolver** | Detect supported issues, explain them, recommend a safe fix, then verify the result |
| 🤖 **AI Assistant** | Ask natural-language questions backed by live Command Center APIs |
| 🔍 **Vector Search** | Search an IRIS-persisted operational knowledge corpus using IRIS Vector Search |
| 🐍 **Embedded Python** | Inspect live diagnostics from IRIS Embedded Python |
| 📦 **ZPM / IPM** | Install the frontend as an IRIS package |
| 🐳 **Docker** | Run IRIS, backend, and frontend together with Docker Compose |

---


## 🩺 Deterministic Issue Resolver

The **Fix Issues** workflow provides a controlled operational path:

```text
Detect
  ↓
Explain
  ↓
Recommend
  ↓
Review
  ↓
Confirm
  ↓
Execute
  ↓
Verify
  ↓
Observe
```

The resolver currently detects supported database-state issues using live IRIS information.

For example:

```text
Issue detected
Database: IPM
State: Dismounted
        ↓
Recommended action
Mount database
        ↓
Review "Why this fix?"
        ↓
Existing Mount workflow
        ↓
Confirmation
        ↓
IRIS operation
        ↓
Fresh verification
        ↓
Issue disappears
        ↓
Execution trace
```

The resolver does **not** autonomously modify IRIS.

---

## 🔍 "Why this fix?"

Supported issues include evidence explaining the recommendation.

The explanation is derived from the same live issue data used by the resolver rather than from a separate AI-generated claim.

This keeps the reasoning visible:

| Evidence | Example |
|---|---|
| Current state | Database is dismounted |
| Safety eligibility | Database is eligible for the supported mount workflow |
| Recommended operation | `database.mount` |
| Verification | Fresh IRIS read confirms the database is mounted |

---

# 🌐 Web Applications & REST Explorer

The Web Apps explorer provides a live view of configured IRIS web applications.

### Configuration areas

- General configuration
- Dispatch & routing
- Authentication & access
- JWT
- CORS
- Sessions & cookies
- Static files & pages
- Python WSGI/ASGI configuration

### REST Explorer

For REST applications, Command Center retrieves the generated REST API definition and exposes:

- HTTP method
- Endpoint path
- Operation ID
- Implementing service method
- Summary and description
- Parameters

```text
IRIS Web Application
        ↓
Management API
        ↓
REST Application
        ↓
Generated API Definition
        ↓
Command Center REST Explorer
```

### Web Sessions

Active session information can be inspected using safe metadata.

Session identifiers are stripped by the backend before the response reaches the browser.

---

# 🔐 Security

Security is organized into focused areas rather than exposing sensitive configuration indiscriminately.

| Area | Visibility |
|---|---|
| **Identity & Access** | Users, roles, resources, access relationships |
| **Authentication** | Services, web authentication, superservers, class access |
| **Wallet** | Collections, resources, secret names and types |
| **X.509** | Credential and certificate metadata without private keys |
| **OAuth2** | Server/client configuration metadata without secrets or tokens |

### Sensitive information is protected

The application deliberately withholds or filters values such as:

- Passwords
- JWTs
- Authorization headers
- Private keys
- Wallet secret values
- OAuth secrets/tokens
- Session identifiers
- Sensitive personal fields

---

# 🔎 Investigation

The Investigation interface exposes the **native IRIS security audit trail**.

### Filters

- Date range
- Event type
- Event
- Username
- Namespace
- Free text
- Sorting

The interface uses the real IRIS audit records and provides a focused detail workspace for individual events.

### Native audit vs Command Center trace

These are complementary sources:

| Source | Answers |
|---|---|
| **IRIS Native Audit** | What security activity did IRIS record? |
| **Command Center Trace** | What controlled operation did Command Center perform? |

Related activity can be connected using the existing time-proximity correlation.

> The two systems remain distinct; correlation does not pretend they share a native correlation ID.

---

# 👁️ Observability

Every controlled administrative operation can produce a structured execution trace.

A trace records safe operational information such as:

- Operation name and ID
- Timestamp
- Duration
- Status
- Authorization events
- Confirmation events
- Execution events
- Verification events
- Safe operation attributes

```text
Authorization
      ↓
Confirmation
      ↓
Execution
      ↓
Verification
      ↓
Completed Trace
```

## Persisting traces in IRIS

Trace persistence can be enabled with:

```env
PERSIST_TRACES_TO_IRIS=true
```

When enabled, Command Center keeps traces in memory and also persists them inside the connected IRIS environment.

```text
                 Command Center
                       │
                       ▼
                Execution Trace
                  /          \
                 /            \
                ▼              ▼
       In-Memory Store    IRIS Trace Storage
```

The persisted trace store is bounded and designed so a persistence problem does not cause the administrative operation itself to fail.

---

# 🤖 AI Assistant

The current AI Assistant intentionally uses a **deterministic intent classifier**, not an external LLM.

It provides a natural-language interface while keeping the operational path inside the existing application architecture.

### Example questions

```text
Is IRIS healthy?

How many processes are running?

Which databases are mounted?

Show me the current namespaces.

What changed recently?
```

### Architecture

```text
User Question
     ↓
Deterministic Intent Detection
     ↓
Existing Command Center API
     ↓
Live IRIS Data
     ↓
Structured Answer
```

The assistant does not receive unrestricted access to privileged IRIS operations.

For administrative actions, the existing authorization, dry-run, confirmation, execution, verification, and trace workflow remains the boundary.

---

# 🔍 IRIS Vector Search

Command Center demonstrates **InterSystems IRIS Vector Search** as an operational knowledge capability.

The knowledge corpus is derived from the application's operation and capability definitions and is persisted in IRIS.

```text
Operation / Capability Knowledge
            ↓
     Deterministic Embedding
            ↓
      IRIS VECTOR column
            ↓
     VECTOR_COSINE search
            ↓
       Top results
```

The feature can be enabled with:

```env
ENABLE_KNOWLEDGE_SEARCH=true
```

The AI Assistant can use this search for operational questions that benefit from capability knowledge.

---

# 🐍 Embedded Python

Command Center also demonstrates **InterSystems IRIS Embedded Python** using live diagnostics from the connected IRIS instance.

The diagnostics include information such as:

- Python version
- Platform
- Hostname
- CPU count
- Load information
- IRIS process information
- Manager-directory disk information
- Memory information
- Installed package count

The backend invokes the controlled diagnostic code inside IRIS and returns safe structured data.

No user-provided text is passed into arbitrary Python imports or invocation parameters.

---

# 🛡️ Safe Administration

Supported administrative operations use a common execution framework.

| Stage | Purpose |
|---|---|
| **Authorize** | Check required IRIS privilege and operation-specific safety rules |
| **Dry Run** | Validate and preview without mutating IRIS |
| **Review** | Show the user what will happen |
| **Confirm** | Require explicit confirmation |
| **Execute** | Perform the controlled IRIS operation |
| **Verify** | Read fresh IRIS state and compare with the requested result |
| **Trace** | Record the operation lifecycle |

### Current supported operation families

| Area | Operations |
|---|---|
| **Journal** | Update Journal Settings |
| **Namespaces** | Create Namespace |
| **Databases** | Create, Mount, Dismount, Integrity Check |
| **Web Applications** | Enable/Disable, Update Description |
| **Users** | Enable/Disable with safety protections |
| **Tasks** | Run Task Now |

Operations are registered centrally so authorization, risk, confirmation, execution, and verification can be handled consistently.

---

# 📊 Dashboard & Explorers

The dashboard provides a live operational snapshot.

### Live areas

- Namespace count
- Database count
- Process count
- Web application count
- Task count
- IRIS uptime
- License usage
- System health indicators
- Database storage
- Process distribution
- Recent operations
- Command Center Issues

The interface intentionally avoids inventing values that the connected IRIS APIs do not provide.

> **If IRIS does not provide a value, Command Center does not pretend that it does.**

---

# 💾 Database Explorer

The Database Explorer provides:

- Database overview
- Mount state
- Database details
- Storage information
- Integrity checking
- Creation
- Mounting
- Dismounting where safe

Safety rules prevent dismounting protected system databases and other databases that are not eligible for the supported workflow.

The integrity check is read-only.

---

# 🗂️ Namespace Explorer

The Namespace Explorer provides:

- Namespace overview
- Namespace details
- Database relationships
- Namespace creation

Namespace creation includes post-action verification and accounts for IRIS configuration propagation.

---

# ⚙️ Process Explorer

The Process Explorer provides:

- Live process list
- State distribution
- Search
- Filtering
- Process details

The application deliberately avoids fabricating process-performance telemetry that is not available from the connected API.

---

# ⏱️ Task Management

Task Management provides:

- Task overview
- Running / suspended / not-running state
- Task details
- Scheduling information
- Execution information
- Safe settings display
- Controlled Run Now workflow for eligible user tasks

Sensitive task settings are recursively redacted before reaching the browser.

---

# 🎯 Demo Activity

Command Center includes a controlled **Demo Activity** workflow for demonstrating the safety model without leaving arbitrary configuration behind.

The standard rehearsal temporarily changes supported configuration and restores the original state.

The **Issue Resolution Rehearsal** demonstrates the complete issue lifecycle:

```text
Temporary issue
     ↓
Detect
     ↓
Explain
     ↓
Recommend
     ↓
Fix through existing operation
     ↓
Verify
     ↓
Restore / clean end state
     ↓
Trace
```

The rehearsal is manually initiated and protected by the same confirmation and execution framework.

---

### Technology stack

| Layer | Technology |
|---|---|
| Platform | InterSystems IRIS 2026.2 |
| Backend | Python, FastAPI, Pydantic |
| Frontend | HTML5, CSS3, Vanilla JavaScript |
| IRIS integration | SysAdmin REST, Management, Security, Audit APIs |
| Native integration | InterSystems IRIS Native API |
| Vector Search | IRIS Vector Search |
| Embedded runtime | IRIS Embedded Python |
| Deployment | Docker, Docker Compose |
| Packaging | ZPM / IPM |
| Testing | pytest, frontend smoke tests |

---

# 🔌 IRIS API Integration

Command Center integrates with several IRIS API surfaces:

```text
                    InterSystems IRIS
                           │
       ┌───────────────────┼───────────────────┐
       │                   │                   │
       ▼                   ▼                   ▼
  SysAdmin API        Management API      Security API
       │                   │                   │
       ▼                   ▼                   ▼
 System State         REST Apps          Users / Roles
 Databases            Route Maps         Resources
 Processes                                Authentication
 Web Apps                                  Wallet
 Tasks
 Journal
       │
       ▼
    Audit API
       │
       ▼
 Investigation

       │
       ▼
    Native API
       │
       ▼
 Trace Persistence / Embedded Python
```

The implementation is based on **observed live IRIS behavior**, not only on the published API specification.

---

# 📦 Deployment

## Docker — recommended

The Docker Compose deployment runs the complete application stack:

| Service | Purpose | Port |
|---|---|---:|
| `backend` | FastAPI application | `8000` |
| `iris` | InterSystems IRIS + Command Center UI | `52773` / `1973` |

The Docker deployment is designed so you do **not** need to install Python or IRIS separately for the standard quick start.

The Command Center frontend is served by IRIS itself. There is no separate Nginx frontend container in the stack.

## ZPM / IPM

The frontend is packaged as an IRIS application named:

```text
iris-command-center
```

The Docker stack installs this package automatically when the IRIS container starts. No manual `zpm load` step is required.

The resulting console is served directly by IRIS:

```text
http://localhost:52773/iris-command-center/index.html
```

The FastAPI backend remains a separate service on port `8000`.

The repository also contains `module.xml`, so the same package can be installed through IPM/ZPM when the package is published to an IPM-compatible registry or Open Exchange.

---

# 🚀 Quick Start

## Prerequisites

- Docker Desktop / Docker Engine
- Docker Compose
- Git

No separate Python or IRIS installation is required for the Docker deployment.

## 1. Clone

```bash
git clone https://github.com/mwaseem75/iris-command-center.git
cd iris-command-center
```

## 2. Configure environment

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

## 3. Start everything

```bash
docker compose up -d --build
```

Check the services:

```bash
docker compose ps
```

The first startup can take longer while IRIS initializes. During startup, the IRIS container automatically loads the `iris-command-center` package from the mounted repository files.

## 4. Open Command Center

```text
http://localhost:52773/iris-command-center/index.html
```

The frontend is served directly by IRIS. No separate frontend server or manual ZPM installation is required.

### Useful endpoints

| URL | Purpose |
|---|---|
| `http://localhost:52773/iris-command-center/index.html` | Command Center |
| `http://localhost:8000/docs` | FastAPI OpenAPI documentation |
| `http://localhost:52773/csp/sys/UtilHome.csp` | IRIS Management Portal |

---

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

Port `5500` is not part of the Docker deployment. It may still be used during frontend development with a local static server such as:

```bash
cd frontend
python -m http.server 5500
```

The backend may retain `http://localhost:5500` in its CORS allowlist for this development workflow.

Example:

```env
IRIS_BASE_URL=http://iris:52773
IRIS_USERNAME=_SYSTEM
IRIS_PASSWORD=change-me
IRIS_NAMESPACE=USER
IRIS_SUPERSERVER_PORT=1972
PERSIST_TRACES_TO_IRIS=true
ENABLE_KNOWLEDGE_SEARCH=true
AUTO_RUN_DEMO_ACTIVITY=true
```

> Use development-only credentials for local Docker deployments. Never commit real passwords, tokens, private keys, or other secrets.

---

## 🔄 Automatic IRIS Package Installation

The Docker deployment keeps the frontend installation reproducible across container recreation.

At IRIS startup:

```text
Repository
   │
   ├── module.xml
   └── frontend/
          │
          ▼
   /home/irisowner/dev
          │
          ▼
   Automatic IPM/ZPM load
          │
          ▼
   IRIS CSP Application
          │
          ▼
/iris-command-center/index.html
```

The package definition and frontend files are mounted read-only into the IRIS container. A small startup script performs the package load together with the existing IRIS startup initialization.

This means a fresh or recreated IRIS container does not depend on a previous manual `zpm "load"` operation.

The intended deployment model is therefore:

```text
docker compose up
       ↓
IRIS starts
       ↓
Package automatically loaded
       ↓
Command Center served by IRIS
       ↓
FastAPI backend on :8000
```

There is deliberately no Nginx frontend container in the production-style Docker stack.

---

# 🧪 Testing & Verification

The project uses automated tests plus live IRIS verification.

## Backend

```bash
pytest
```

Coverage includes:

- API routes
- Authorization
- Operation execution
- Dry-run behavior
- Post-action verification
- Database safety
- Web application safety
- User safety
- Task safety
- Security filtering
- Wallet protection
- Session protection
- Investigation
- Observability
- Trace persistence
- Issue resolution
- Vector Search
- Embedded Python
- Demo workflows

## Frontend

Frontend smoke tests and JavaScript syntax checks cover important UI behavior and integration points.

## Live IRIS verification

Important workflows have also been exercised against a real IRIS 2026.2 environment, including:

- Namespace creation
- Database creation
- Database integrity checks
- Database mount/dismount safety
- Journal configuration
- Web application inspection
- Security inspection
- Wallet inspection
- Audit investigation
- Execution tracing
- Vector Search
- Embedded Python
- Issue detection and resolution

---

# 🖼️ Screens & Visuals

The repository's README includes the multi-screen product tour.

```text
assets/
└── iris-command-center-multiple-screens.gif
```

The product tour is intentionally made from actual Command Center screens rather than mock UI.

---

# 🎬 Suggested Demo

A concise end-to-end demonstration can follow this sequence:

```text
1. Dashboard
      ↓
2. Inspect live system state
      ↓
3. Explore Web Apps / REST endpoints
      ↓
4. Open Security
      ↓
5. Investigate native IRIS audit activity
      ↓
6. Open Observability
      ↓
7. Show a controlled operation
      ↓
8. Dry Run
      ↓
9. Confirm
      ↓
10. Execute
      ↓
11. Verify
      ↓
12. Inspect execution trace
      ↓
13. Use Fix Issues
      ↓
14. Review "Why this fix?"
      ↓
15. Resolve and verify the issue
      ↓
16. Ask the AI Assistant a live question
      ↓
17. Show Vector Search / Embedded Python
```

---

# 🧩 Project Structure

```text
iris-command-center/
│
├── backend/
│   ├── app/
│   │   ├── auth/
│   │   ├── models/
│   │   ├── observability/
│   │   ├── operations/
│   │   ├── routes/
│   │   ├── services/
│   │   └── main.py
│   └── tests/
│
├── frontend/
│   ├── index.html
│   ├── css/
│   ├── js/
│   └── assets/
│
├── assets/
│   └── iris-command-center-multiple-screens.gif
│
├── spec/
│   └── mainspec_v2.json
│
├── docker-compose.yml
├── Dockerfile
├── module.xml
├── .env.example
└── README.md
```

---

# 🛡️ Security Model

The application follows a few non-negotiable rules.

| Principle | Implementation |
|---|---|
| **No implicit trust** | The frontend is not a security boundary |
| **Privilege-aware** | Operations require their configured IRIS privilege |
| **Dry-run first** | Supported mutations can be previewed without writes |
| **Explicit confirmation** | Mutations require deliberate confirmation |
| **Verify after mutation** | Fresh IRIS state is checked after execution |
| **Unknown operations denied** | Unsupported actions are rejected |
| **Secrets protected** | Sensitive fields are filtered before browser exposure |
| **No credential traces** | Passwords, JWTs, and authorization headers are excluded |
| **AI stays inside the boundary** | Assistant reuses existing APIs rather than bypassing them |

---

# 🧠 Development Philosophy

### Verify First

Test IRIS API behavior against a real IRIS instance.

### Build Incrementally

Implement and validate one capability at a time.

### Reuse Proven Patterns

Authorization, operation execution, verification, observability, and UI patterns should be reused rather than duplicated.

### Keep the Browser Simple

Security and business rules belong in the backend.

### Prefer Real Data

Use live IRIS responses whenever possible.

### Protect Sensitive Data

Remove sensitive values before they reach the browser or traces.

### Fail Safely

Unknown, unsupported, or ambiguous operations should be rejected rather than guessed.

---

# 🤝 Contributing

Contributions, API discoveries, documentation improvements, and UI enhancements are welcome.

When adding an IRIS capability:

1. Verify the API against a real IRIS instance.
2. Document observed behavior.
3. Add the backend API client method.
4. Add the appropriate model.
5. Add tests.
6. Protect sensitive fields.
7. Add authorization for mutations.
8. Add dry-run support where appropriate.
9. Add post-action verification.
10. Update the documentation.

---

# 📄 License

This project is licensed under the **MIT License**.

---

<p align="center">

### IRIS Command Center

**Observe. Investigate. Act—safely.**

`OBSERVE` → `INVESTIGATE` → `ACT SAFELY` → `VERIFY` → `TRACE`

**A modern operational interface for InterSystems IRIS.**

</p>




The core idea is simple:

> **Make IRIS administration easier to understand and safer to operate without bypassing the underlying IRIS security and management model.**

### Who is it for?

| Role | Useful for |
|---|---|
| 🛠️ **IRIS Administrators** | Monitor systems, inspect configuration, and perform controlled administration |
| 🔎 **Support & Operations Teams** | Investigate incidents and follow operational traces |
| 💻 **IRIS Developers & Integrators** | Explore REST applications, APIs, namespaces, databases, and processes |
| 🔐 **Security Teams** | Review users, roles, resources, authentication, wallets, X.509, and OAuth2 visibility |
| 🤖 **AI / Automation Developers** | See how natural-language assistance can reuse safe operational APIs |


The project is built around a simple operational philosophy:

> **Observe what is happening. Investigate why it is happening. Act only when it is safe to do so.**

---

------------------------------------------------------------------
------------------------------------------------------------------









## Trace Persistence in IRIS

Command Center can persist its execution traces **inside the connected InterSystems IRIS instance**.

This makes observability more than a browser-only feature.

```text
Administrative Operation
          │
          ▼
   Execution Trace
          │
          ├──────────────► In-Memory Trace Store
          │
          └──────────────► IRIS Trace Storage
                                  │
                                  ▼
                         InterSystems IRIS
```

This creates an important operational relationship:

> **The environment being administered can also retain the operational trace of the administration activity.**

---

## Configurable Persistence

Trace persistence is controlled by a configuration flag:

```text
PERSIST_TRACES_TO_IRIS=false
```

When disabled:

```text
Operation
   ↓
Execution Trace
   ↓
In-Memory Store
```

When enabled:

```text
Operation
   ↓
Execution Trace
   ├──────────► In-Memory Store
   │
   └──────────► IRIS Trace Storage
```

This makes trace persistence an explicit deployment choice.

---

## Why Persist Traces in IRIS?

The Command Center trace and IRIS native audit trail provide complementary information.

| Source | Answers |
|---|---|
| **Command Center Trace** | What operation did Command Center perform? |
| **IRIS Native Audit** | What security activity did IRIS record? |

Together they provide a stronger investigation story.

```text
                 InterSystems IRIS
                       │
          ┌────────────┼─────────────┐
          │            │             │
          ▼            ▼             ▼
     System State   Native Audit   Command Center
                                    Trace Storage
```

---

## Trace Lifecycle

```text
User Request
     │
     ▼
Authorization
     │
     ▼
Dry Run
     │
     ▼
Confirmation
     │
     ▼
Execution
     │
     ▼
Verification
     │
     ▼
Trace Completed
     │
     ├──────────────► In-Memory
     │
     └──────────────► IRIS
                         │
                         ▼
                  Persistent Trace
```

The trace persistence layer is designed so that a persistence failure does not cause the administrative operation itself to fail.

---

# AI Assistant

**AI-assisted operations are a first-class capability of IRIS Command Center.**

The current assistant intentionally uses a **deterministic intent classifier** rather than an external LLM.

This provides a controlled foundation for natural-language operational assistance without giving an AI model unrestricted administrative access.

---

## AI Architecture

```text
┌──────────────────────┐
│        User          │
│                      │
│ "How many processes  │
│  are running?"       │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ Intent Classifier    │
│                      │
│ Deterministic        │
│ Operation Matching   │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ Existing Command     │
│ Center API           │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ InterSystems IRIS    │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ Safe Operational     │
│ Response             │
└──────────────────────┘
```

The important design principle is:

> **The AI layer uses the same application APIs as the rest of the Command Center.**

It does not receive a hidden privileged path to IRIS.

---

## Example Questions

```text
Show me the current IRIS system status.

How many processes are running?

Show me the current namespaces.

How many databases are mounted?
```

---

## AI Safety Boundary

For read-only requests:

```text
User
 ↓
AI Intent
 ↓
Existing Read-only API
 ↓
IRIS
 ↓
Answer
```

For future administrative actions:

```text
AI
 ↓
Approved Operation
 ↓
Authorization
 ↓
Dry Run
 ↓
Human Confirmation
 ↓
Execute
 ↓
Verify
 ↓
Trace
```

This ensures that adding more sophisticated AI in the future does not require bypassing the application's safety architecture.

---

# Safe Administration

Administrative operations use a common safety framework.

```text
┌─────────────────────┐
│    User Request     │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│    Authorization    │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│   Risk Assessment   │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│      Dry Run        │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│ Explicit Confirmation│
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│ Execute against IRIS│
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│ Post-Action Verify  │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│   Execution Trace   │
└─────────────────────┘
```

---

## Authorization

The backend independently evaluates whether the requested operation is permitted.

The frontend is never treated as a trusted security boundary.

---

## Dry Run

Dry-run mode:

- Does not mutate IRIS
- Validates the requested operation
- Checks authorization
- Produces an operation preview

---

## Explicit Confirmation

A mutating action requires deliberate user confirmation before execution.

This protects against accidental execution caused by:

- Misclicks
- Ambiguous UI state
- Automation errors
- Stale browser state
- AI suggestions

---

## Post-Action Verification

Command Center does not assume that a successful HTTP response means the desired state was achieved.

After execution:

```text
Requested State
      │
      ▼
IRIS Mutation
      │
      ▼
Fresh IRIS Read
      │
      ▼
Compare
      │
      ├── Match ──────► Verified
      │
      └── Mismatch ───► Verification Failed
```

---

# Dashboard & System Explorers

The Command Center provides several live system explorers.

| Explorer | Purpose |
|---|---|
| **Dashboard** | Operational overview and navigation |
| **Namespaces** | Namespace configuration and relationships |
| **Databases** | Database state, information, and administration |
| **Processes** | Live process investigation |
| **Web Apps** | Web application configuration |
| **Tasks** | Scheduled task investigation |
| **Security** | Identity, authentication, and wallet visibility |
| **Investigation** | Audit and operational investigation |

The explorers use live IRIS responses rather than demonstration data.

---

# Database Operations

The Database Explorer provides:

- Database overview
- Database details
- Database information
- Integrity checking
- Database creation
- Mount workflow

Database creation and mounting use controlled administrative workflows.

The integrity check is read-only and preserves the raw IRIS console result.

---

# Namespace Operations

The Namespace Explorer provides:

- Namespace overview
- Namespace details
- Database relationships
- Namespace creation

Namespace creation includes post-action verification.

IRIS configuration propagation is taken into account during verification.

---

# Process Investigation

The Process Explorer provides:

- Live process list
- State distribution
- Search
- Filtering
- Process details

The application intentionally avoids fabricating process performance telemetry that is not exposed by the API.

---

# Task Management

Task Management provides:

- Task overview
- Running state
- Suspended state
- Not Running state
- Task details
- Scheduling information
- Execution information
- Safe settings display

Sensitive task settings are recursively redacted before reaching the browser.

---

# Investigation

The Investigation interface exposes the native IRIS security audit trail.

Filters include:

- Date range
- Event type
- Username
- Free text
- Sorting

The Command Center trace provides a complementary operational perspective.

```text
Command Center Trace
        │
        │
        ├──── Operation lifecycle
        │
        ▼
Investigation
        ▲
        │
        │
IRIS Native Audit
        │
        └──── IRIS security activity
```

---

# Real IRIS Data

A central principle of the project is:

> **If the connected IRIS API does not provide a value, Command Center should not pretend that it does.**

The application does not fabricate:

- CPU graphs
- Memory trends
- Web application traffic
- Request latency
- Error rates
- Health scores
- Alerts

unless those values are actually available from the connected environment.

This keeps the console honest about what IRIS actually reports.

---

# API Behavior vs Documentation

The project validates API behavior against a live IRIS environment.

Actual API responses can differ from the published specification.

For example, IRIS responses can use wrapper structures such as:

```json
{
  "status": {},
  "console": [],
  "result": {}
}
```

The development approach is therefore:

```text
Official API Specification
           +
Live IRIS Behavior
           ↓
Actual Application Model
```

This avoids building the application around assumptions that are not true for the running IRIS version.

---

# Security Principles

## No implicit trust

The frontend is never a trusted security boundary.

## Privilege-aware

Administrative operations are evaluated against the required IRIS privileges.

## Explicit confirmation

Mutations require deliberate user confirmation.

## Verify after mutation

The final state is read from IRIS after execution.

## AI is controlled

AI assistance cannot silently bypass the operation framework.

## Secrets are protected

Passwords, tokens, private keys, wallet values, and session identifiers are not unnecessarily exposed.

## Unknown operations are denied

Unsupported operations are rejected rather than guessed.

## Dry-run is non-mutating

A dry-run must never modify IRIS.

## Credentials do not enter traces

JWTs, Authorization headers, passwords, and other credentials are excluded from execution traces.

---

# Technology Stack

| Layer | Technology |
|---|---|
| **Platform** | InterSystems IRIS 2026.2 |
| **Backend** | Python · FastAPI · Pydantic |
| **Frontend** | HTML5 · CSS3 · Vanilla JavaScript |
| **IRIS Integration** | SysAdmin REST API · Management API · Security API · Audit API |
| **Native Integration** | InterSystems IRIS Native API |
| **Infrastructure** | Docker · Docker Compose |
| **Testing** | pytest · Frontend Smoke Tests |
| **Development** | Visual Studio Code · Git · GitHub |
| **Observability** | Structured execution traces · Optional IRIS persistence |
| **AI** | Deterministic operational intent classifier |

---

# IRIS API Integration

Command Center integrates with multiple IRIS API surfaces.

```text
                    InterSystems IRIS
                           │
          ┌────────────────┼──────────────────┐
          │                │                  │
          ▼                ▼                  ▼
     SysAdmin API    Management API     Security API
          │                │                  │
          │                │                  │
          ▼                ▼                  ▼
     System State      REST Apps        Users
     Databases         Route Maps       Roles
     Processes                           Resources
     Web Apps                            Services
     Tasks                               Authentication
     Journal                             Wallet
          │
          ▼
       Audit API
          │
          ▼
    Investigation

          │
          ▼
      Native API
          │
          ▼
  Optional Trace Persistence
```

---

# Project Structure

```text
iris-command-center/
│
├── backend/
│   ├── app/
│   │   ├── auth/
│   │   ├── models/
│   │   ├── observability/
│   │   ├── operations/
│   │   ├── routes/
│   │   ├── services/
│   │   └── main.py
│   │
│   └── tests/
│
├── frontend/
│   ├── index.html
│   ├── css/
│   ├── js/
│   │   ├── api.js
│   │   ├── dashboard.js
│   │   ├── namespaces.js
│   │   ├── databases.js
│   │   ├── processes.js
│   │   ├── web-apps.js
│   │   ├── tasks.js
│   │   ├── security-access.js
│   │   ├── security-wallet.js
│   │   └── ...
│   └── assets/
│
├── docs/
│   ├── images/
│   ├── api-capability-matrix.md
│   ├── phase-1-environment-report.md
│   └── ...
│
├── spec/
│   └── mainspec_v2.json
│
├── docker-compose.yml
├── CLAUDE.md
└── README.md
```

---

# Installation

## Clone the Repository

```bash
git clone https://github.com/mwaseem75/iris-command-center.git
cd iris-command-center
```

## Start IRIS

```bash
docker compose up -d
```

Verify the container:

```bash
docker ps
```

## Create Python Environment

```bash
python -m venv .venv
```

### Windows

```bash
.venv\Scripts\activate
```

### Linux / macOS

```bash
source .venv/bin/activate
```

## Install Dependencies

```bash
pip install -r backend/requirements.txt
```

## Start the Backend

```bash
uvicorn backend.app.main:app --reload --port 8000
```

## Start the Frontend

```bash
cd frontend
python -m http.server 5500
```

Open:

```text
http://localhost:5500
```

---

# Configuration

Trace persistence is configurable.

```text
PERSIST_TRACES_TO_IRIS=false
```

### Disabled

Execution traces remain in the application trace store.

### Enabled

Execution traces are also persisted inside IRIS.

Sensitive credentials should never be committed to source control.

Do not store:

```text
IRIS passwords
JWTs
API keys
Private keys
Wallet secrets
OAuth secrets
```

in Git.

---

# Testing & Verification

The project uses several levels of verification.

## Backend Tests

Backend tests cover:

- API routes
- Authorization
- Operation execution
- Dry-run behavior
- Post-action verification
- Security filtering
- Wallet protection
- Web application safety
- Session protection
- Observability
- Investigation

Run:

```bash
pytest
```

---

## Frontend Smoke Tests

Frontend smoke tests validate important:

- UI behavior
- JavaScript structure
- API integration
- Security-sensitive display behavior
- Required controls

---

## Live IRIS Verification

Important features are also verified against the actual development IRIS environment.

Examples include:

- Namespace creation
- Database creation
- Database integrity check
- Journal configuration
- Web application inspection
- Security inspection
- Wallet inspection
- Audit investigation
- Execution tracing


WORKFLOW
                    IRIS COMMAND CENTER
                            │
                            ▼
                       Dashboard
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
          Web Apps       Security      Processes
             │              │
             ▼              ▼
       REST Explorer     Users/Roles
             │              │
             ▼              ▼
        Web Sessions   Authentication
             │              │
             └───────┬──────┘
                     ▼
                Investigation
                     │
                     ▼
             Safe Operation
                     │
                     ▼
                  Dry Run
                     │
                     ▼
                Confirmation
                     │
                     ▼
                  Execute
                     │
                     ▼
                  Verify
                     │
                     ▼
               Execution Trace
                     │
                     ▼
              Persist in IRIS
```

Then demonstrate the AI Assistant:

```text
"How many processes are running?"
```

followed by:

```text
"Show me the current IRIS system status."
```

---

# Contest Focus

IRIS Command Center is being developed for the:

**InterSystems Programming Contest — Build Your Own Management Portal**

The primary contest capability is:

> **Manage Web Apps and Explore REST APIs**

The project extends this into a broader operational platform covering:

- Web applications
- REST APIs
- Security
- Tasks
- Databases
- Namespaces
- Processes
- Investigation
- Observability
- AI-assisted operations
- Safe administrative workflows

The goal is to demonstrate not only API integration, but a practical and reusable approach to IRIS administration.

---

# Community Value

The project is intended to be useful as a community reference and potentially as a foundation for future IRIS tooling.

It demonstrates patterns for:

```text
IRIS API Integration
        ↓
Privilege-aware Operations
        ↓
Safe Mutations
        ↓
Verification
        ↓
Observability
        ↓
IRIS Trace Persistence
        ↓
Investigation
        ↓
Controlled AI Assistance
```

Potential community applications include:

- Administration consoles
- Support tooling
- Developer utilities
- REST API discovery
- Security review tools
- Incident investigation tools
- DevOps integrations
- AI-assisted IRIS operations

---

# Online Demo

An online demonstration is planned.

The intended architecture is:

```text
┌──────────────────┐
│   GitHub Pages   │
│                  │
│  Documentation   │
│  Landing Page    │
└────────┬─────────┘
         │ HTTPS
         ▼
┌──────────────────┐
│ FastAPI Backend  │
│                  │
│ Safety Boundary  │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Dedicated Demo   │
│ InterSystems IRIS│
└──────────────────┘
```

The public environment should use:

- A dedicated non-production IRIS instance
- Non-sensitive demonstration data
- HTTPS
- Restricted CORS
- Restricted credentials
- No production secrets

---

# Roadmap

## Completed

### Foundation

- FastAPI backend
- Vanilla JavaScript frontend
- IRIS API client
- Authentication
- Authorization framework
- Operation framework
- Observability

### Observe

- Dashboard
- Namespace Explorer
- Database Explorer
- Process Explorer
- Web Apps Explorer
- Task Management
- Security visibility

### Investigate

- Investigation UI
- Native IRIS audit integration
- Execution traces
- Optional IRIS trace persistence
- Web sessions
- REST endpoint exploration

### Act Safely

- Namespace creation
- Database creation
- Database mount workflow
- Database integrity check
- Journal configuration operation
- Web application enable/disable workflow
- Authorization
- Dry-run
- Confirmation
- Post-action verification

### AI

- Deterministic operational assistant
- Read-only intent routing
- Reuse of existing Command Center APIs

---

## Planned

### Security

- X.509 credential management
- OAuth 2.0 configuration management
- Additional controlled security operations

### Operations

- Additional database operations
- Additional web application operations
- Additional task operations

### Investigation

- Additional correlation capabilities
- Expanded operational timelines
- Additional investigation views

### Deployment

- Online demonstration
- HTTPS deployment
- Demo environment hardening

### Community

- Developer documentation
- Tutorials
- Contribution guidelines
- Community feedback

---

# Documentation

Project documentation includes:

- API capability research
- IRIS environment verification
- Architecture documentation
- Security design
- Development notes
- Contest documentation

Important project files:

```text
docs/
spec/mainspec_v2.json
CLAUDE.md
```

The API capability matrix documents administrative APIs discovered and verified against the development IRIS environment.

---

# Development Philosophy

## Verify First

Test IRIS API behavior against a real IRIS instance.

## Build Incrementally

Implement and validate one capability at a time.

## Reuse Proven Patterns

Authorization, operation execution, verification, observability, and UI patterns should be reused rather than duplicated.

## Keep the Browser Simple

Security and business rules belong in the backend.

## Prefer Real Data

Use live IRIS responses whenever possible.

## Protect Sensitive Data

Sensitive values should be removed before they reach the browser or execution traces.

## Fail Safely

Unknown, unsupported, or ambiguous operations should be rejected rather than guessed.

---

# Contributing

Contributions, ideas, API discoveries, documentation improvements, and UI enhancements are welcome.

When adding a new IRIS capability:

1. Verify the API against a real IRIS instance.
2. Document the observed behavior.
3. Add the backend API client method.
4. Add the appropriate model.
5. Add tests.
6. Protect sensitive fields.
7. Add authorization for mutations.
8. Add dry-run support where appropriate.
9. Add post-action verification.
10. Update the documentation.

---

# License

This project is licensed under the **MIT License**.

---

<p align="center">

### IRIS Command Center

**Observe. Investigate. Act—safely.**

```text
       OBSERVE
          │
          ▼
     INVESTIGATE
          │
          ▼
     ACT SAFELY
          │
          ▼
       VERIFY
          │
          ▼
        TRACE
          │
          ▼
   PERSIST IN IRIS
```

**A modern operational interface for InterSystems IRIS.**

</p>
