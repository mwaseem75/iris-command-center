# IRIS Command Center

**Observe. Investigate. Act—safely.**

A modern, permission-aware operations and investigation console for **InterSystems IRIS**, built on the IRIS SysAdmin REST APIs, Management APIs, Security APIs, Audit APIs, and Native API.

<p align="center">
  <img width="650" alt="image" src="https://github.com/user-attachments/assets/dd29861d-7f46-454e-ab0a-6aca372e2f7e" />

</p>

<p align="center">
  <a href="https://www.intersystems.com/">
    <img src="https://img.shields.io/badge/Platform-InterSystems%20IRIS-009688?style=flat-square" alt="Platform">
  </a>
  <a href="https://fastapi.tiangolo.com/">
    <img src="https://img.shields.io/badge/Backend-FastAPI-009688?style=flat-square" alt="Backend">
  </a>
  <a href="https://developer.mozilla.org/en-US/docs/Web/JavaScript">
    <img src="https://img.shields.io/badge/Frontend-Vanilla%20JavaScript-F7DF1E?style=flat-square" alt="Frontend">
  </a>
  <a href="https://www.docker.com/">
    <img src="https://img.shields.io/badge/Deployment-Docker-2496ED?style=flat-square" alt="Docker">
  </a>
  <a href="https://www.python.org/">
    <img src="https://img.shields.io/badge/Language-Python-3776AB?style=flat-square" alt="Python">
  </a>
  <a href="https://opensource.org/licenses/MIT">
    <img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="License">
  </a>
</p>

<p align="center">
  <strong>Observe</strong> ·
  <strong>Investigate</strong> ·
  <strong>Act Safely</strong> ·
  <strong>Verify</strong> ·
  <strong>Trace</strong>
</p>

---

## Table of Contents

- [Project Vision](#project-vision)
- [The Problem](#the-problem)
- [The Solution](#the-solution)
- [Core Operational Model](#core-operational-model)
- [Features at a Glance](#features-at-a-glance)
- [Application Architecture](#application-architecture)
- [Application Workflow](#application-workflow)
- [Community Use Cases](#community-use-cases)
- [Web Apps & REST Explorer](#web-apps--rest-explorer)
- [Security & Access](#security--access)
- [Observability & Trace Persistence](#observability--trace-persistence)
- [AI Assistant](#ai-assistant)
- [Safe Administration](#safe-administration)
- [Dashboard & System Explorers](#dashboard--system-explorers)
- [Task Management](#task-management)
- [Investigation](#investigation)
- [Real IRIS Data](#real-iris-data)
- [Security Principles](#security-principles)
- [Technology Stack](#technology-stack)
- [IRIS API Integration](#iris-api-integration)
- [Project Structure](#project-structure)
- [Installation](#installation)
- [Configuration](#configuration)
- [Testing & Verification](#testing--verification)
- [Screenshots](#screenshots)
- [Demo Flow](#demo-flow)
- [Contest Focus](#contest-focus)
- [Online Demo](#online-demo)
- [Roadmap](#roadmap)
- [Documentation](#documentation)
- [Development Philosophy](#development-philosophy)
- [Contributing](#contributing)
- [License](#license)

---

# Project Vision

InterSystems IRIS provides a powerful set of capabilities for system administration, application management, security, monitoring, and investigation.

However, these capabilities are exposed across multiple management areas and API surfaces.

**IRIS Command Center** brings those capabilities together into a single modern operational console.

The goal is not to replace the underlying IRIS administration APIs.

The goal is to make them:

- Easier to explore
- Easier to understand
- Safer to use
- Easier to investigate
- Easier to extend
- More accessible to developers and administrators

The project is built around a simple operational philosophy:

> **Observe what is happening. Investigate why it is happening. Act only when it is safe to do so.**

---

# The Problem

An IRIS administrator or support engineer may need to move between:

```text
Management Portal
       │
       ├── System configuration
       ├── Web applications
       ├── Tasks
       └── Security
       
SysAdmin REST APIs
       │
       ├── Namespaces
       ├── Databases
       ├── Processes
       └── Configuration

Management APIs
       │
       └── REST applications / endpoint definitions

Security APIs
       │
       ├── Users
       ├── Roles
       ├── Resources
       └── Authentication

Audit APIs
       │
       └── Security investigation

Custom scripts
```

This can make operational investigation fragmented.

There are also additional challenges:

### Fragmented visibility

Information about a single incident may be distributed across several IRIS APIs.

### Privilege complexity

Different operations require different administrative privileges.

### Risky mutations

A configuration change should not become an unchecked REST request.

### Sensitive information

Security and management APIs may expose information that should never reach the browser.

### AI safety

An AI assistant should not receive unrestricted access to privileged administrative operations.

---

# The Solution

IRIS Command Center provides a unified operational layer around these capabilities.
<img width="1536" alt="image" src="https://github.com/user-attachments/assets/e43f7850-f6a0-4eff-a792-bb9a70dc4f9e" />



The browser does not directly perform IRIS administrative operations.

The backend provides the application, authorization, safety, and observability boundary.

---

# Core Operational Model

The Command Center is organized around five stages:

```text
┌───────────────┐
│    OBSERVE    │
│               │
│ System State  │
│ Configuration │
│ Security      │
└───────┬───────┘
        │
        ▼
┌───────────────┐
│  INVESTIGATE  │
│               │
│ Audit         │
│ Sessions      │
│ Traces        │
│ Relationships │
└───────┬───────┘
        │
        ▼
┌───────────────┐
│  ACT SAFELY   │
│               │
│ Authorize     │
│ Dry Run       │
│ Confirm       │
│ Execute       │
└───────┬───────┘
        │
        ▼
┌───────────────┐
│    VERIFY     │
│               │
│ Fresh IRIS    │
│ State Check   │
└───────┬───────┘
        │
        ▼
┌───────────────┐
│     TRACE     │
│               │
│ What happened │
│ When          │
│ Result        │
└───────────────┘
```

This model is shared across the application's administrative operations.

---

# Features at a Glance

Rather than treating every screen as an isolated feature, the Command Center groups capabilities into operational areas.

| Capability Area | What it provides | Primary purpose |
|---|---|---|
| **Observe** | Dashboard, Namespaces, Databases, Processes, Tasks | Understand current IRIS state |
| **Web Apps** | Web application configuration, REST APIs, sessions | Manage and investigate IRIS applications |
| **Security** | Users, Roles, Resources, Services, Authentication, Wallet | Understand security posture |
| **Investigate** | IRIS audit trail, execution traces, session information | Find and understand operational activity |
| **Act Safely** | Authorization, dry-run, confirmation, execution, verification | Perform controlled administrative changes |
| **Observability** | Structured execution traces | Understand what Command Center did |
| **IRIS Persistence** | Optional trace persistence inside IRIS | Keep operational traces with the managed environment |
| **AI Assistant** | Deterministic operational intent handling | Natural-language access to safe operations |
| **REST Explorer** | Generated REST endpoint discovery | Understand IRIS REST applications |
| **Community Platform** | Reusable API and safety patterns | Provide building blocks for IRIS developers |

---

# Application Architecture

The architecture deliberately separates the browser from the IRIS administrative APIs.

```text
┌───────────────────────────────────────────────────────────────┐
│                           BROWSER                             │
│                                                               │
│  Dashboard     Namespaces      Databases      Processes       │
│  Web Apps      REST Explorer   Tasks          Security        │
│  Investigation Observability   AI Assistant                 │
│                                                               │
│             HTML + CSS + Vanilla JavaScript                   │
└───────────────────────────────┬───────────────────────────────┘
                                │
                                │ HTTP
                                ▼
┌───────────────────────────────────────────────────────────────┐
│                       FASTAPI BACKEND                         │
│                                                               │
│ Authentication                                                │
│ Authorization                                                 │
│ Operation Registry                                            │
│ Validation                                                    │
│ Risk Assessment                                               │
│ Dry Run                                                        │
│ Confirmation                                                   │
│ Execution                                                     │
│ Verification                                                  │
│ Secret Filtering                                               │
│ ★ Observability / Trace Generation ★                          │
└───────────────────────────────┬───────────────────────────────┘
                                │
               ┌────────────────┼────────────────┐
               │                │                │
               ▼                ▼                ▼
       ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
       │ SysAdmin API │ │ Management   │ │ Security /   │
       │              │ │ API          │ │ Audit API    │
       └──────────────┘ └──────────────┘ └──────────────┘
               │                │                │
               └────────────────┼────────────────┘
                                ▼
                    ┌──────────────────────┐
                    │  INTERSYSTEMS IRIS   │
                    │                      │
                    │       2026.2         │
                    │                      │
                    │ ★ Trace Storage ★    │
                    └──────────────────────┘
```

---

# Application Workflow

## Read Operation

A normal read operation follows:

```text
Browser
   │
   ▼
FastAPI Route
   │
   ▼
IRIS API Client
   │
   ▼
InterSystems IRIS
   │
   ▼
Live IRIS Response
   │
   ▼
Validated Backend Model
   │
   ▼
Browser
```

---

## Administrative Operation

A mutating operation follows a stricter path:

```text
User Request
     │
     ▼
Authorization
     │
     ▼
Risk Assessment
     │
     ▼
Dry Run
     │
     ▼
Review
     │
     ▼
Explicit Confirmation
     │
     ▼
Execute against IRIS
     │
     ▼
Post-Action Verification
     │
     ▼
Execution Trace
     │
     ▼
Result
```

---

# Community Use Cases

IRIS Command Center is designed to be useful beyond the contest demonstration.

## 1. IRIS Administration Console

Provide a unified operational view for common IRIS administration activities.

```text
Dashboard
    │
    ├── Namespaces
    ├── Databases
    ├── Processes
    ├── Web Apps
    ├── Tasks
    └── Security
```

---

## 2. Incident Investigation

When something goes wrong, the operator can move from system state into investigation.

```text
Dashboard
   ↓
Web App
   ↓
Application Configuration
   ↓
Active Sessions
   ↓
Processes
   ↓
Security
   ↓
IRIS Audit
   ↓
Command Center Trace
```

This provides a practical investigation path without requiring the operator to manually assemble information from multiple interfaces.

---

## 3. REST API Discovery

Developers working with IRIS REST applications can explore:

```text
REST Application
      ↓
Generated API Definition
      ↓
HTTP Method
      ↓
Endpoint Path
      ↓
Operation ID
      ↓
Implementation Method
      ↓
Parameters
```

This can be useful when learning, documenting, troubleshooting, or integrating with an existing IRIS REST application.

---

## 4. Security Review

Security teams can use the Command Center to navigate relationships such as:

```text
User
  ↓
Role
  ↓
Resource
  ↓
Access
```

alongside:

```text
Services
   ↓
Authentication
   ↓
Superserver
   ↓
TLS
```

The interface provides visibility without attempting to make security decisions on behalf of the administrator.

---

## 5. Controlled Configuration Changes

For supported administrative operations:

```text
Requested Change
      ↓
Dry Run
      ↓
Review
      ↓
Confirmation
      ↓
Execute
      ↓
Verify
      ↓
Trace
```

This provides a consistent safety model across operations.

---

## 6. Web Application Troubleshooting

An administrator can inspect a web application from several perspectives:

```text
Web Application
      │
      ├── General Configuration
      ├── Authentication
      ├── CORS
      ├── JWT
      ├── Sessions
      └── REST Endpoints
```

---

## 7. Task Investigation

When a scheduled task behaves unexpectedly:

```text
Find Task
   ↓
Check State
   ↓
Review Schedule
   ↓
Review Execution
   ↓
Inspect Settings
```

Sensitive settings are filtered before reaching the browser.

---

## 8. AI-Assisted Operations

The AI Assistant provides a natural-language entry point to safe operational information.

Examples:

```text
How many processes are running?

Show me the current IRIS system status.

Show me the current namespaces.

How many databases are mounted?
```

The assistant reuses the same application APIs rather than creating a privileged shortcut.

---

## 9. Community Development Platform

The project can also serve as a reference for developers who want to:

- Consume IRIS SysAdmin APIs from Python
- Build IRIS administration tooling
- Implement privilege-aware operations
- Add dry-run workflows
- Verify configuration changes
- Explore IRIS REST applications
- Protect sensitive API responses
- Add AI safely to administrative tooling

---

# Web Apps & REST Explorer

Web application management is one of the major capabilities of IRIS Command Center.

The explorer provides a live view of configured IRIS web applications and distinguishes between REST and CSP applications.

## Web Application Details

Configuration is organized into:

- General
- Dispatch & Routing
- Authentication & Access
- JWT
- CORS
- Sessions & Cookies
- Static Files & Pages
- Python WSGI/ASGI

---

## REST Endpoint Explorer

For REST applications, Command Center retrieves the generated REST API definition.

Endpoint information includes:

- HTTP method
- Path
- Operation ID
- Implementing service method
- Summary
- Description
- Parameters

Endpoints can be searched and filtered.

```text
IRIS Web Application
        ↓
Management API
        ↓
REST Application
        ↓
Generated API Specification
        ↓
Command Center
        ↓
Searchable REST Explorer
```

---

## Web Sessions

Active web sessions can be inspected using safe session metadata such as:

- User
- Application
- Client information
- Process information

Session identifiers are removed by the backend before the response reaches the browser.

---

# Security & Access

Security is organized around three complementary areas:

```text
┌─────────────────────────────────────────┐
│              SECURITY                   │
├─────────────────────────────────────────┤
│                                         │
│  Identity & Access                      │
│    Users                                │
│    Roles                                │
│    Resources                            │
│                                         │
│  Authentication                         │
│    Services                             │
│    Web Authentication                   │
│    Superservers                         │
│    Class Access                         │
│                                         │
│  Wallet                                 │
│    Collections                          │
│    Secret Metadata                      │
│                                         │
└─────────────────────────────────────────┘
```

---

## Identity & Access

### Users

User information includes:

- Name
- Full name
- Enabled state
- Type
- Namespace
- Roles
- Authentication information

Sensitive personal fields are withheld.

---

### Roles

Role information includes:

- Role name
- Description
- Granted roles
- Resource grants
- Owners
- Privileged relationships

---

### Resources

Resource information includes:

- Resource name
- Description
- Public permission
- Resource information
- Role access

---

## Authentication Posture

The Authentication area provides visibility into:

- IRIS services
- Web authentication
- Superservers
- Class access

Configurations that may deserve further review, such as enabled unauthenticated services or superserver configurations without TLS, can be highlighted in the UI.

---

## Wallet

The Wallet interface provides safe visibility into wallet metadata.

It exposes:

- Collections
- Edit resources
- Use resources
- Secret names
- Secret types

Secret values are never displayed.

The backend uses explicit field allowlists so sensitive fields cannot simply flow through to the browser.

---

# Observability & Trace Persistence

**Observability is a first-class capability of IRIS Command Center.**

Every controlled administrative operation can produce a structured execution trace.

```text
Operation
    │
    ├── Authorization
    │
    ├── Confirmation
    │
    ├── Execution
    │
    └── Verification
            │
            ▼
      Execution Trace
```

A trace can contain:

- Operation name
- Operation ID
- Timestamp
- Duration
- Status
- Authorization events
- Confirmation events
- Execution events
- Verification events
- Safe operation attributes

Sensitive credentials and authorization headers are not persisted in traces.

---

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

---

# Screenshots

Application screenshots are maintained under:

```text
docs/images/
```

Recommended screenshots:

```text
docs/images/dashboard.png
docs/images/namespaces.png
docs/images/databases.png
docs/images/processes.png
docs/images/web-apps.png
docs/images/rest-explorer.png
docs/images/security.png
docs/images/investigation.png
```

Example:

![IRIS Command Center Dashboard](docs/images/dashboard.png)

> Screenshot filenames should be updated to match the actual files committed to the repository.

---

# Demo Flow

A strong demonstration flow is:

```text
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
