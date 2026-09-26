# ✨ IRIS Command Center

**Observe. Investigate. Act—safely.**

A modern operational console for **InterSystems IRIS** that brings monitoring, administration, investigation, security visibility, issue resolution, and operational tracing into one place.
It combines live IRIS system information with controlled administrative workflows, native audit investigation, structured execution traces, security visibility, and a deterministic AI Assistant.
<p align="center">
  <img width="2496" height="1268" alt="image" src="https://github.com/user-attachments/assets/69d79579-0e6c-4c75-91f8-3d83af191257" />
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
| 📊 **Dashboard** | View live system state, databases, processes, web apps, tasks, resources, alerts, and recent activity |
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
| 🩺 **Issue Resolver** | Detect supported issues, understand why a fix is recommended, apply the safe workflow, and verify the result |
| 🤖 **AI Assistant** | Ask natural-language questions backed by live Command Center APIs |
| 🔍 **Vector Search** | Search an IRIS-persisted operational knowledge corpus using IRIS Vector Search |
| 🐍 **Embedded Python** | Inspect live diagnostics from IRIS Embedded Python |
| 🎬 **Demo Activity** | Demonstrate controlled operations, issue resolution, verification, restoration, and execution tracing |

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

### 3. Start everything

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
<img width="2173" alt="image" src="https://github.com/user-attachments/assets/1cbac9e2-644d-408f-a9e9-2ce7cc26b47e" />


### 🛠️ IRIS System Administration (Operations)

Monitor an IRIS instance, explore its configuration, and perform supported administrative tasks from one operational console.
<img width="2191" height="1195" alt="image" src="https://github.com/user-attachments/assets/d7d8a782-9cc7-47b4-a12c-80655eb40030" />


### 🚨 Investigation

Start with an observed issue, inspect system state and configuration, investigate native IRIS audit activity, and follow related Command Center execution traces.
The interface uses the real IRIS audit records and provides a focused detail workspace for individual events.
<img width="2177" height="1241" alt="image" src="https://github.com/user-attachments/assets/88b48323-fba2-4eed-ad3d-ef086f6206a4" />


### 🌐 Web Application 

Inspect web application configuration, authentication, CORS, JWT, sessions, cookies, REST endpoints, and related application state. Explore generated REST API definitions when developing, integrating with, documenting, or troubleshooting an IRIS REST application.
<img width="2175" height="1128" alt="image" src="https://github.com/user-attachments/assets/6157798b-b62e-4f3b-91e3-974b66381898" />


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
<img width="2172" height="1082" alt="image" src="https://github.com/user-attachments/assets/54083e46-6aee-4d3c-86a7-74de644cd462" />
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



### 🩺 Database Troubleshooting & Recovery

Detect supported database-state issues, understand the evidence behind the recommended fix, execute the existing safe operation, and verify that the issue is resolved.
<img width="2178" height="1133" alt="image" src="https://github.com/user-attachments/assets/4875ea65-f29b-4623-888f-1ad8f9f889bd" />


### 🤖 AI-Assisted 

Ask natural-language questions about live IRIS data while keeping the assistant inside the same controlled application API boundary.
The current AI Assistant intentionally uses a **deterministic intent classifier**, not an external LLM.

It provides a natural-language interface while keeping the operational path inside the existing application architecture.
<img width="2175" height="1147" alt="image" src="https://github.com/user-attachments/assets/52a5785f-321d-4451-bb6c-00067b6e7869" />


### 👁️ Observability

Understand two complementary perspectives:
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
IRIS Native Audit
      ↓
What security activity did IRIS record?

Command Center Trace
      ↓
What operation did Command Center perform?
```
<img width="2183" height="1162" alt="image" src="https://github.com/user-attachments/assets/131b5172-4491-4303-9907-a258dda623e8" />

---
## Advanced Capabilities
### 🩺 Deterministic Issue Resolver

The **Fix Issues** workflow provides a controlled operational path:

<img width="1827" alt="image" src="https://github.com/user-attachments/assets/958632a0-9b9e-4d54-970a-1f11c3ceaaf5" />

---


---
### Native audit vs Command Center trace

These are complementary sources:

| Source | Answers |
|---|---|
| **IRIS Native Audit** | What security activity did IRIS record? |
| **Command Center Trace** | What controlled operation did Command Center perform? |

Related activity can be connected using the existing time-proximity correlation.

> The two systems remain distinct; correlation does not pretend they share a native correlation ID.

---

## Persisting traces in IRIS

<img width="1753" height="691" alt="image" src="https://github.com/user-attachments/assets/02c0089a-2f1d-4ade-8b19-c39682775e3a" />


---

# 🔍 IRIS Vector Search

Command Center demonstrates **InterSystems IRIS Vector Search** as an operational knowledge capability.

<img width="1754" height="683" alt="image" src="https://github.com/user-attachments/assets/0d1df68b-6c57-4185-9d23-adfe1f765fc4" />

---

# 🎯 Demo Activity

Command Center includes a controlled **Demo Activity** workflow for demonstrating the safety model without leaving arbitrary configuration behind.

<img width="1765" alt="image" src="https://github.com/user-attachments/assets/af2f6967-0f3d-40db-bf30-e17b686dc23d" />

---
### 🧪 Testing & Verification

The project uses automated tests plus live IRIS verification.
<img width="1749" height="725" alt="image" src="https://github.com/user-attachments/assets/87883946-9eca-4eb6-9db3-5693854c4357" />

### Trace Persistence in IRIS

Command Center can persist its execution traces **inside the connected InterSystems IRIS instance**.
This makes observability more than a browser-only feature.
<img width="1749" alt="image" src="https://github.com/user-attachments/assets/154dfd30-10f5-40d9-8dc7-bf1a2c1b9a91" />



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










