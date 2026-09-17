# IRIS Command Center

A management portal for InterSystems IRIS, built against the SysAdmin REST API. No
frontend framework — plain HTML, CSS, and ES modules, served as static files.

The project targets IRIS Community Edition and IRIS for Health Community Edition,
and was started as an entry for InterSystems' "Build Your Own Management Portal"
contest. It talks to IRIS entirely through its own public REST API; there is no
backend server of its own beyond a small local dev proxy (see below).

## What it does today

**Authentication.** The login screen doesn't assume a particular IRIS version. It
tries JWT login first (`POST /login`, available from IRIS 2026.2) and falls back
to HTTP Basic transparently if that route doesn't exist, so the same build works
against older instances without configuration. Sessions live in memory only —
nothing is written to `localStorage` or a cookie the app controls, so refreshing
the page always returns to the login screen. That's deliberate.

**Dashboard.** Pulls live data from the five monitoring endpoints IRIS actually
exposes: subsystem health, active processes and CSP sessions, license usage,
journal/routine activity, and shared-memory allocation. The REST API itself
reports no CPU% or memory% — every card here still reflects a real field, not
an invented average. Manual and auto-refresh, plus a computed health banner
(healthy / warning / critical) based on actual subsystem status and alert
counts. A separate card above it runs a real CPU/memory health score via
Embedded Python — see below.

**Processes.** List, search, and inspect running processes; suspend, resume,
terminate, or broadcast a message to attached terminals. Every one of those
actions opens a confirmation dialog showing the exact HTTP request before it's
sent — method, path, and body — not a paraphrase of it.

**Tasks.** Scheduled task list, upcoming runs, and run history, plus task
manager controls (run / suspend / resume the scheduler daemon itself). Individual
tasks can be run on demand, suspended, resumed, or deleted. Task creation and
editing — a form with roughly thirty scheduling fields — isn't built yet.

**Databases, namespaces, devices.** Local database directories with disk and
volume detail, mount/dismount/compact/integrity-check actions, and full CRUD;
a read-only view of namespace-to-database bindings; namespace create/edit/
delete; device and device-subtype management; telnet and device I/O settings.

**Security.** Users, roles, and resources (full CRUD); system services;
auditing — enable/disable, event configuration, filtered record search, purge,
and copy to another namespace; SQL table and admin privilege grant/revoke;
encryption startup settings and activated key list. X.509 credentials and
OAuth2 (client and server) aren't built yet — see the scope note below.

**Wallets.** Collection and secret management, built around one hard
constraint: this API has no endpoint, anywhere, that returns a secret's
value once written. The page doesn't fight that — secret forms are
write-only, the confirmation dialog and activity log both show a redacted
request rather than the real one, and nothing resembling a value is ever
logged to the console.

**Web applications.** List, detail, create, edit, and delete, plus each app's
%-class access rules. The detail view for any REST-dispatch application hands
off directly into the REST Explorer rather than treating them as unrelated
screens.

**REST Explorer.** Discovers every REST-enabled application on the instance —
not by guessing, but by asking IRIS's own Management API (`/api/mgmnt`) to
describe itself, which turns out to be genuinely self-documenting: it hands
back a real OpenAPI 2.0 definition for anything it lists. From there you can
browse an app's actual paths and methods, fill in parameters, and execute —
GET requests run immediately, anything else goes through the same confirm-
and-preview dialog as every mutating action elsewhere in this app, because
"safe request execution" has to mean something even for endpoints this app
didn't define itself.

**Health Report.** The one place this app steps outside the SysAdmin REST API
on purpose. There's genuinely no endpoint anywhere in it that reports CPU or
memory usage, so that data comes from an Embedded Python method running
inside IRIS itself — a real `psutil` call, not a proxy metric — exposed
through a small custom REST app (`/api/health`) this project defines and
deploys the same way it defines any other web application. IRIS-specific
inputs (license headroom, failed tasks, audit alerts, databases nearing
capacity) aren't re-derived in Python; they're the same already-verified
data the dashboard fetches, just handed to the scorer. The result — a 0-100
score, status, and concrete recommendations — shows as a compact card on the
Dashboard and in full on its own page. See
[`docs/health-analyzer.md`](docs/health-analyzer.md) for the design and how
to deploy it.

**Ask IRIS.** A grounded chat assistant, built on IRIS's own native SQL
Vector Search and LangChain. It answers questions about this portal using
only chunks retrieved from this project's own documentation — never from
the model's general knowledge alone — and every answer cites the sources it
came from. The OpenAI API key it needs never touches the frontend: it's
stored using this app's own Wallets feature and read server-side from
Embedded Python, the same "no secrets in the browser" rule the rest of the
app follows. Rebuilding the index is a real, costed API call, so it goes
through the same confirm-and-preview dialog as any other mutating action
here. See [`docs/ask-iris.md`](docs/ask-iris.md) for the design and how to
deploy it.

**Logs.** Journal files, per-file detail, filtered record search within a
file, and journal configuration, plus an Activity tab listing every
background task this IRIS instance has run — not just this session's, since
it's server-side history, not a browser-side log. Record search runs
asynchronously on the server (a 202 response with the real result polled
from a `Location` header) the same way audit search does on the Security
page; that pattern is centralized in `js/api/async-api.js` and reused here
rather than re-implemented.

**Everywhere.** Every state-changing call in the app goes through the same
pipeline: preview the request → confirm → execute → record. The result lands in
an activity panel (the small counter next to your username in the top bar) so
you can see what's been done this session and exactly what was sent and
received, without digging through browser dev tools.

Every module from the original spec is now built. `docs/api-matrix.md` has
the full picture of what's implemented, what's intentionally out of scope,
and why.

## Requirements

- Any modern browser (the app uses native ES modules, `<details>`, and
  `fetch` — nothing exotic, but no IE11 either)
- Docker and Docker Compose for the one-command setup (Option A below); or,
  for the manual path (Option B), [Node.js](https://nodejs.org) 18+ to run
  the bundled dev server (no build step, no npm install, no dependencies)
  plus any IRIS instance to point it at

## Getting started

### Option A: Docker (recommended)

```bash
docker compose up --build
```

One command. This builds an IRIS image with the Embedded Python bonus
modules, their pip dependencies, the docs corpus Ask IRIS indexes, and the
ISOE ObjectScript classes all wired up automatically on first boot —
compiled, web applications created, default password unexpired — plus a
second container running this project's own `dev-server.mjs` (the same
server described in Option B below, not a separate production-only path).
Open `http://localhost:8080` once both containers report healthy; login
with `_SYSTEM` / `SYS`.

HealthAnalyzer works immediately — no setup, real `psutil` data from the
first request. Ask IRIS needs an OpenAI API key added afterward via the
Wallets page (a real external credential is never baked into an image); it
shows a clear "not configured" state until then. See
[`docs/docker.md`](docs/docker.md) for what the image does, including three
real bugs (one in the base image's own entrypoint) found and fixed getting
this to boot cleanly.

### Option B: Manual setup

#### 1. Start an IRIS instance

```bash
docker run -d --name iris-cc -p 52773:52773 -p 1972:1972 intersystemsdc/iris-community:2026.2
```

The version tag matters: JWT login only exists from 2026.2 onward. Earlier
tags (including `latest`, which currently resolves to 2026.1) work fine too —
the app just falls back to Basic auth and hides the couple of features that
genuinely don't exist on older releases (see `docs/api-matrix.md` for the
specifics).

Community images ship with an expired default password that the REST API has
no way to reset on its own, so clear it once via an ObjectScript session:

```bash
docker exec -i iris-cc iris session IRIS -U %SYS <<'EOF'
Do ##class(Security.Users).UnExpireUserPasswords("*")
Halt
EOF
```

The default account on a fresh container is `_SYSTEM` / `SYS` (also
`SuperUser` / `SYS`).

#### 2. Serve the app

```bash
node dev-server.mjs --port 8080 --target http://localhost:52773
```

This is a small, dependency-free static file server that also proxies
`/api/*` requests to your IRIS instance. Routing everything through one
origin means the browser never sees a cross-origin request, so there's no
CORS configuration to fight with locally — it behaves the same way the app
will in production, where IRIS serves the static files itself from the same
web application as the API.

Open `http://localhost:8080`.

#### 3. Optional: deploy the Embedded Python health score

The Dashboard and Health Report page work without this — they just show the
feature as unavailable. To enable the real CPU/memory score, install
`psutil` inside the container, copy `iris/python/health_analyzer.py` onto
IRIS's Python path, compile the two classes in `iris/classes/ISOE/`, and
create the `/api/health` web application pointing at
`ISOE.HealthAnalyzerREST`. Full steps in
[`docs/health-analyzer.md`](docs/health-analyzer.md).

#### 4. Optional: deploy Ask IRIS

Also works without this — the page just shows a "not configured" state.
Enabling it needs LangChain (`pip3 install langchain langchain-openai
langchain-community`), the `iris/python/ask_iris.py` module plus a small
docs corpus copied alongside it, the two classes in `iris/classes/ISOE/`,
the `/api/ai` web application, and an OpenAI API key stored via the
Wallets page. Full steps in [`docs/ask-iris.md`](docs/ask-iris.md).

### Configuration

Runtime settings — API base paths, request timeout, and a couple of flags
reserved for later phases — live in [`js/config.js`](js/config.js) and are
edited directly; there's no build step to inject them through. Any individual
setting can be overridden for a single session via a query parameter instead,
which is mostly useful for pointing at a second IRIS instance without editing
files:

```
http://localhost:8080/?apiBaseUrl=http://localhost:52774/api/admin
```

## How it's put together

No React, Vue, Angular, or bundler — the brief for this project ruled out
frameworks, and it turned out not to need one. Pages are plain functions that
build and return DOM nodes; a hash-based router (`#/dashboard`, `#/processes`,
...) swaps the content region in and out. A handful of small, deliberately
boring utilities do the repetitive work: `data-table.js` for searchable/
paginated tables, `crud-section.js` for the list → detail → create/edit →
delete pattern that most admin resources share, `perform-action.js` for the
confirm/preview/execute/record pipeline mentioned above.

The one piece of real engineering underneath the UI is version tolerance: IRIS
2026.2 introduced a new generation of this API (`/v2/...`, JWT auth, a handful
of new endpoints) alongside the previous one. Rather than hard-coding against
whichever version happened to be running during development, the app checks
`GET /info`'s reported API version once at login and routes accordingly. A
second thing worth knowing if you're reading the source: a few endpoints
(bulk audit record search, database integrity checks) are asynchronous —
the immediate response is empty, and the real result has to be polled for at
a URL the server returns in a `Location` header rather than the response
body. `js/api/async-api.js` handles that once; everything else calls it and
gets an ordinary-looking promise back. Several other gaps between what the
official spec documents and what the live API actually does turned up
building this — they're written up in `docs/api-matrix.md` rather than
quietly worked around.

```
index.html          entry point
css/                design tokens, layout, components — plain CSS, no preprocessor
js/
  app.js            boots the shell and router
  router.js         hash routing + auth guards
  state.js          session state and a tiny pub/sub
  config.js         runtime configuration
  api/              one thin wrapper per REST resource
  services/         auth/session and the activity log
  components/       reusable UI: modal, data table, toasts, ...
  pages/            one file per route
  utils/            shared helpers (forms, CRUD scaffolding, confirm/execute)
iris/
  python/           health_analyzer.py, ask_iris.py — Embedded Python modules, plus their tests
  classes/ISOE/      ObjectScript bridge + REST dispatch for /api/health and /api/ai
docker/             Dockerfile + first-boot install script — see docs/docker.md
docker-compose.yml  one-command setup: docker compose up --build
docs/               architecture notes, the full API matrix, security notes
dev-server.mjs      static file server + API proxy, for local development
package.json        no dependencies — exists only so Node treats js/*.js as ES
                     modules when running the test suite below
```

## Testing

```bash
npm test                                                    # frontend logic (38 tests)
python -m unittest discover -s iris/python/tests -v         # Embedded Python (26 tests)
```

`npm test` needs no install step — there are no dependencies, `package.json`
exists purely so Node's module resolver treats `js/*.js` as ES modules (the
browser never reads it; `index.html` already loads every script as a module
directly). It runs Node's built-in test runner (`node:test`) against
`js/tests/`, covering the logic that doesn't need a browser to exercise:
session/privilege state, the activity log, the `{status, console, result}`
response-envelope unwrapping (including a regression test for a real Phase 9
bug — a caught server-side error silently returning `{}` instead of
throwing), and the REST Explorer's credential-prompt caching (a regression
test for a real Phase 7 race condition — two concurrent callers each opening
their own login prompt, only one ever answerable). DOM-heavy pages and
components aren't covered here; those were verified live against a running
IRIS instance throughout development instead — see the phase-by-phase
findings in `docs/api-matrix.md`.

The Python suite (`iris/python/tests/`) covers the pure logic in
`health_analyzer.py` and `ask_iris.py` — scoring thresholds, chunking — with
a plain stdlib interpreter, no IRIS or pip packages required.

## Documentation

- [`docs/api-matrix.md`](docs/api-matrix.md) — every endpoint the app calls: method,
  path, parameters, privilege required, and whether it's read-only or mutating,
  cross-checked against a live instance rather than taken on faith from the spec
- [`docs/health-analyzer.md`](docs/health-analyzer.md) — the Embedded Python
  health score: inputs, outputs, error handling, deployment, and why IRIS-
  specific metrics come from the REST API rather than guessed ObjectScript calls
- [`docs/ask-iris.md`](docs/ask-iris.md) — the Vector Search + LangChain
  assistant: how retrieval and grounding work, how the OpenAI key is stored
  and read without ever reaching the frontend, error handling, and deployment
- [`docs/docker.md`](docs/docker.md) — what the one-command Docker setup does,
  and three real bugs (including one in the base image itself) found and
  fixed to get a clean automated first boot
- [`docs/architecture.md`](docs/architecture.md) — request lifecycle, frontend
  layering, the confirm/preview/execute/record pattern in full, and the
  three-layer Embedded Python bridge shape shared by both bonus features
- [`docs/security.md`](docs/security.md) — the principles behind every
  security-relevant decision in this app: credential handling, redaction,
  privilege gating, and what "no guessed API contracts" means for security
- [`docs/demo-script.md`](docs/demo-script.md) — a ~10-minute walkthrough
  covering every required module and bonus feature

## A note on scope

Every required module is built. A few narrower things were left out on
purpose rather than half-built: namespace mapping (global/package/routine),
task creation/editing, creating a new REST application from a pasted OpenAPI
document, and — within Security — X.509 credentials and OAuth2 client/server
configuration, which alone is around twenty endpoints and probably deserves
its own page rather than a seventh tab bolted onto Security. None of this is
silently faked in the meantime: an unbuilt page says so in the sidebar rather
than pretending to work.

## Disclaimer

This application can make real administrative changes to whatever IRIS
instance it's pointed at — suspending processes, deleting databases, and so
on. Point it at a test or development instance, not production.

## License

MIT — see [LICENSE](LICENSE).
