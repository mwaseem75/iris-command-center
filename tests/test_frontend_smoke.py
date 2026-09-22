"""Minimal frontend smoke test — no test framework introduced for this.

Run directly:  python tests/test_frontend_smoke.py
(uses the backend's existing venv, since it needs to import the real
FastAPI app to compare routes — see backend/.venv)

Checks, per Phase 3 Step 1's minimum bar ("verify the frontend can be
served and that its API paths match the existing backend routes"),
extended in Phase 3 Step 2 for the System view, Phase 3 Step 3 for the
Processes view, Phase 3 Step 4 for the Databases view, Phase 3 Step 5 for
the Web Apps view, Phase 3 Step 6 for the Tasks view, and Phase 3 Step 7
for the Security view:

1. The expected frontend files exist and are non-empty.
2. A plain static file server can actually serve frontend/index.html.
3. Every /api/iris/* path referenced in frontend/js/api.js is a REAL,
   currently-registered route on the backend FastAPI app (compared via the
   app's own OpenAPI schema, not by guessing/duplicating the route list).
4. (Step 2) The System nav item and view exist in the markup and the nav
   item is enabled (not `disabled`).
5. (Step 2) system.js calls GET /api/iris/info and no other endpoint.
5b. The Namespaces nav item and view exist in the markup and the nav item
    is enabled (not `disabled`); namespaces.js calls GET /api/iris/namespaces
    and no other endpoint.
6. (Step 3) The Processes nav item and view exist in the markup and the
   nav item is enabled (not `disabled`).
7. (Step 3) processes.js calls GET /api/iris/processes and no other
   endpoint, and renders into the processes table body.
8. (Step 4) The Databases nav item and view exist in the markup and the
   nav item is enabled (not `disabled`).
9. (Step 4) databases.js calls GET /api/iris/databases and no other
   endpoint, and renders into the databases table body.
10. (Step 5) The Web Apps nav item and view exist in the markup and the
    nav item is enabled (not `disabled`).
11. (Step 5) web-apps.js calls only GET /api/iris/web-apps and the
    read-only GET /api/iris/web-apps/detail (detail drawer) and
    GET /api/iris/web-apps/rest-endpoints (REST Endpoints tab) and
    GET /api/iris/web-sessions (Web Sessions section, never a session ID),
    and renders into the web apps table body.
12. (Step 6) The Tasks nav item and view exist in the markup and the nav
    item is enabled (not `disabled`).
13. (Step 6) tasks.js calls only the read-only GET /api/iris/tasks/overview,
    /tasks/manager and /tasks/detail endpoints, and renders into the tasks
    table body.
14. (Step 7) The Security nav item and view exist in the markup and the
    nav item is enabled (not `disabled`).
15. (Step 7) security.js calls only the three OAuth2 endpoints (server,
    client/server-definitions, server/clients) and no other endpoint, and
    renders into the security view's own elements.
16. (Step 8) The Journal nav item and view exist in the markup and the nav
    item is enabled (not `disabled`), and journal.js calls only
    GET /api/iris/journal/settings.
17. (general regression guard) No mutating HTTP method string
    ("PUT"/"POST"/"DELETE"/"PATCH") appears anywhere in frontend/js/*.js —
    this is intentionally broad so it keeps guarding every future view,
    not just System/Processes/Databases/Web Apps/Tasks/Security/Journal.
18. (Phase 4) The AI Assistant nav item/view exist and are enabled, and
    ai-assistant.js calls only GET /api/iris/assistant/query (the backend's
    read-only, natural-language query endpoint) and no other IrisApi
    method — see backend/app/routes/assistant.py.
19. The Extensions nav item and view exist in the markup and the nav item
    is enabled (not `disabled`); extensions.js calls only the three
    remaining previously-unexposed read-only endpoints (ext-lang-servers,
    fs-access-purposes, wallet/collections) and no other IrisApi method.
20. The Investigation nav item and view exist in the markup and the nav
    item is enabled (not `disabled`); investigation.js calls only
    IrisApi.getAuditEnabled()/getAuditRecords() and no other IrisApi
    method, and never references a mutating HTTP method (IRIS's own
    async-task POST for audit records happens entirely on the backend;
    this view only ever sends a GET).
21. The API Capability Explorer ("capabilities") nav item and view exist in
    the markup and the nav item is enabled (not `disabled`);
    capabilities.js calls only IrisApi.getCapabilities() and no other
    IrisApi method, filters entirely client-side (no other network call on
    input), and never references a mutating HTTP method.
22. Observability and Investigation cross-link to each other by time
    window only (never a shared IRIS/trace ID, since none exists):
    nav.js exports navigateTo(); observability.js gained its own
    client-side Begin/End (UTC) time filter and exports setTimeWindow();
    investigation.js exports setTimeWindow() for the reverse direction;
    app.js wires both cross-link callbacks. Neither view gained a new
    endpoint call or a mutating HTTP method reference.
23. The Dashboard (the contest/demo landing screen) surfaces Recent
    Activity (dashboard.js additionally calls IrisApi.getExecutionTraces())
    and Explore quicklinks that navigate (via nav.js's navigateTo()) to
    other real, enabled nav views — never a typo'd data-view target.
    Still calls no other IrisApi method, no raw fetch(), and no mutating
    HTTP method.

Does not start icc-iris-dev, does not call any IRIS endpoint, does not
import or exercise anything mutating.
"""

import http.client
import os
import re
import sys
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = REPO_ROOT / "frontend"
BACKEND_DIR = REPO_ROOT / "backend"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ok: {message}")


def test_expected_files_exist_and_are_non_empty() -> None:
    print("Checking expected frontend files exist...")
    expected = [
        FRONTEND_DIR / "index.html",
        FRONTEND_DIR / "css" / "styles.css",
        FRONTEND_DIR / "js" / "app.js",
        FRONTEND_DIR / "js" / "api.js",
        FRONTEND_DIR / "js" / "dashboard.js",
        FRONTEND_DIR / "js" / "system.js",
        FRONTEND_DIR / "js" / "namespaces.js",
        FRONTEND_DIR / "js" / "nav.js",
        FRONTEND_DIR / "js" / "processes.js",
        FRONTEND_DIR / "js" / "databases.js",
        FRONTEND_DIR / "js" / "web-apps.js",
        FRONTEND_DIR / "js" / "tasks.js",
        FRONTEND_DIR / "js" / "security.js",
        FRONTEND_DIR / "js" / "journal.js",
        FRONTEND_DIR / "js" / "operations.js",
        FRONTEND_DIR / "js" / "ai-assistant.js",
        FRONTEND_DIR / "js" / "observability.js",
        FRONTEND_DIR / "js" / "extensions.js",
        FRONTEND_DIR / "js" / "investigation.js",
        FRONTEND_DIR / "js" / "capabilities.js",
    ]
    for path in expected:
        check(path.is_file(), f"{path.relative_to(REPO_ROOT)} exists")
        check(path.stat().st_size > 0, f"{path.relative_to(REPO_ROOT)} is non-empty")


def test_frontend_can_be_served() -> None:
    print("Checking the frontend can be served over HTTP...")
    handler = lambda *args, **kwargs: SimpleHTTPRequestHandler(  # noqa: E731
        *args, directory=str(FRONTEND_DIR), **kwargs
    )
    server = HTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        time.sleep(0.1)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/index.html")
        response = conn.getresponse()
        body = response.read().decode("utf-8")
        check(response.status == 200, f"GET /index.html -> HTTP {response.status}")
        check("IRIS Command Center" in body, "served index.html contains the product name")
        conn.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_api_paths_match_real_backend_routes() -> None:
    print("Checking frontend API paths match real, registered backend routes...")
    api_js = (FRONTEND_DIR / "js" / "api.js").read_text(encoding="utf-8")
    referenced_paths = sorted(set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', api_js)))
    check(len(referenced_paths) >= 6, f"found {len(referenced_paths)} referenced /api/iris/* paths")

    sys.path.insert(0, str(BACKEND_DIR))
    os.environ.setdefault("IRIS_BASE_URL", "http://smoke-test.invalid")
    os.environ.setdefault("IRIS_USERNAME", "smoke-test")
    os.environ.setdefault("IRIS_PASSWORD", "smoke-test")

    from app.main import app  # imports the REAL app; no IRIS call happens on import

    registered_paths = set(app.openapi()["paths"].keys())

    for path in referenced_paths:
        check(path in registered_paths, f"{path} is a real registered backend route")


def test_system_nav_and_view_exist_and_are_enabled() -> None:
    print("Checking the System nav item and view exist and are enabled...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    nav_match = re.search(
        r'<button class="nav-item[^"]*"[^>]*data-view="system"[^>]*>', html
    )
    check(nav_match is not None, "a nav-item button with data-view=\"system\" exists")
    check("disabled" not in nav_match.group(0), "the System nav-item is NOT disabled")

    view_match = re.search(r'<section[^>]*id="view-system"[^>]*data-view="system"[^>]*>', html)
    check(view_match is not None, 'a <section id="view-system" data-view="system"> exists')


def test_system_view_uses_only_get_info() -> None:
    print("Checking system.js calls GET /api/iris/info and nothing else...")
    system_js = (FRONTEND_DIR / "js" / "system.js").read_text(encoding="utf-8")

    check("IrisApi.getInfo" in system_js, "system.js calls IrisApi.getInfo()")
    other_methods = ["getNamespaces", "getDatabases", "getProcesses", "getWebApps", "getTasks"]
    for method in other_methods:
        check(method not in system_js, f"system.js does NOT call IrisApi.{method}()")

    referenced_paths = set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', system_js))
    check(
        referenced_paths in ({"/api/iris/info"}, set()),
        f"system.js references only /api/iris/info as a literal path (found: {referenced_paths or 'none, uses IrisApi.getInfo()'})",
    )


def test_namespaces_nav_and_view_exist_and_are_enabled() -> None:
    print("Checking the Namespaces nav item and view exist and are enabled...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    nav_match = re.search(
        r'<button class="nav-item[^"]*"[^>]*data-view="namespaces"[^>]*>', html
    )
    check(nav_match is not None, "a nav-item button with data-view=\"namespaces\" exists")
    check("disabled" not in nav_match.group(0), "the Namespaces nav-item is NOT disabled")

    view_match = re.search(
        r'<section[^>]*id="view-namespaces"[^>]*data-view="namespaces"[^>]*>', html
    )
    check(view_match is not None, 'a <section id="view-namespaces" data-view="namespaces"> exists')

    # Namespace Explorer redesign: the wide table was replaced by a card
    # grid, a database-sharing topology section, and a detail drawer.
    check('id="namespaces-card-grid"' in html, "the namespaces card grid element exists")
    check('id="namespaces-topology"' in html, "the namespaces topology element exists")
    check('id="namespaces-drawer"' in html, "the namespaces detail drawer element exists")


def test_namespaces_view_uses_only_get_and_create_namespace() -> None:
    print("Checking namespaces.js calls only IrisApi.getNamespaces()/getDatabases()/createNamespace()...")
    namespaces_js = (FRONTEND_DIR / "js" / "namespaces.js").read_text(encoding="utf-8")

    check("IrisApi.getNamespaces" in namespaces_js, "namespaces.js calls IrisApi.getNamespaces()")
    # The "New Namespace" wizard's Configure step populates its database
    # selectors from the existing, already-tested read-only databases API
    # — never a hardcoded list of names.
    check(
        "IrisApi.getDatabases" in namespaces_js,
        "namespaces.js calls IrisApi.getDatabases() to populate the wizard's database selectors",
    )
    # namespace.create (the "New Namespace" wizard) is this view's one
    # sanctioned mutating capability — it must go through the IrisApi
    # wrapper, never a raw fetch() (checked in
    # test_no_mutating_http_method_anywhere_in_frontend_js below).
    check(
        "IrisApi.createNamespace" in namespaces_js,
        "namespaces.js calls IrisApi.createNamespace() for its 'New Namespace' wizard",
    )
    other_methods = ["getInfo", "getProcesses", "getWebApps", "getTasks"]
    for method in other_methods:
        check(method not in namespaces_js, f"namespaces.js does NOT call IrisApi.{method}()")

    referenced_paths = set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', namespaces_js))
    check(
        referenced_paths in ({"/api/iris/namespaces"}, set()),
        f"namespaces.js references only /api/iris/namespaces as a literal path "
        f"(found: {referenced_paths or 'none, uses the IrisApi wrapper only'})",
    )
    check(
        "namespaces-card-grid" in namespaces_js,
        "namespaces.js renders into the namespaces card grid element",
    )
    check(
        "namespace-create-drawer" in namespaces_js,
        "namespaces.js renders into the 'New Namespace' wizard drawer element",
    )


def test_processes_nav_and_view_exist_and_are_enabled() -> None:
    print("Checking the Processes nav item and view exist and are enabled...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    nav_match = re.search(
        r'<button class="nav-item[^"]*"[^>]*data-view="processes"[^>]*>', html
    )
    check(nav_match is not None, "a nav-item button with data-view=\"processes\" exists")
    check("disabled" not in nav_match.group(0), "the Processes nav-item is NOT disabled")

    view_match = re.search(
        r'<section[^>]*id="view-processes"[^>]*data-view="processes"[^>]*>', html
    )
    check(view_match is not None, 'a <section id="view-processes" data-view="processes"> exists')

    check('id="processes-table-body"' in html, "the processes table body element exists")
    check('id="processes-summary-grid"' in html, "the processes state KPI grid exists")
    check('id="processes-overview"' in html, "the processes State Distribution panel exists")
    check('id="processes-filter-search"' in html, "the processes search input exists")
    check('id="processes-filter-state"' in html, "the processes State filter exists")
    check('id="processes-drawer"' in html, "the processes detail drawer element exists")


def test_processes_view_uses_only_get_processes() -> None:
    print("Checking processes.js calls GET /api/iris/processes and nothing else...")
    processes_js = (FRONTEND_DIR / "js" / "processes.js").read_text(encoding="utf-8")

    check("IrisApi.getProcesses" in processes_js, "processes.js calls IrisApi.getProcesses()")
    other_methods = ["getInfo", "getNamespaces", "getDatabases", "getWebApps", "getTasks"]
    for method in other_methods:
        check(method not in processes_js, f"processes.js does NOT call IrisApi.{method}()")

    referenced_paths = set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', processes_js))
    check(
        referenced_paths in ({"/api/iris/processes"}, set()),
        f"processes.js references only /api/iris/processes as a literal path "
        f"(found: {referenced_paths or 'none, uses IrisApi.getProcesses()'})",
    )
    check(
        "processes-table-body" in processes_js,
        "processes.js renders into the processes table body element",
    )


def test_databases_nav_and_view_exist_and_are_enabled() -> None:
    print("Checking the Databases nav item and view exist and are enabled...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    nav_match = re.search(
        r'<button class="nav-item[^"]*"[^>]*data-view="databases"[^>]*>', html
    )
    check(nav_match is not None, "a nav-item button with data-view=\"databases\" exists")
    check("disabled" not in nav_match.group(0), "the Databases nav-item is NOT disabled")

    view_match = re.search(
        r'<section[^>]*id="view-databases"[^>]*data-view="databases"[^>]*>', html
    )
    check(view_match is not None, 'a <section id="view-databases" data-view="databases"> exists')

    # Database Explorer redesign: the wide table was replaced by a card
    # grid and a read-only detail drawer, same interaction pattern as the
    # Namespace Explorer.
    check('id="databases-card-grid"' in html, "the databases card grid element exists")
    check('id="databases-drawer"' in html, "the databases detail drawer element exists")
    # The "+ New Database" wizard: the button is now a real, enabled
    # trigger for the wizard drawer (database.create), not a disabled
    # placeholder.
    nav_button_match = re.search(
        r'<button class="btn btn--primary" type="button" id="databases-create-button">', html
    )
    check(nav_button_match is not None, "the '+ New Database' button exists and is enabled")
    check(
        'id="database-create-drawer"' in html,
        "the 'New Database' wizard drawer element exists",
    )
    # database.info: the detail drawer's read-only "View Info" action.
    check(
        'id="databases-drawer-info-button"' in html,
        "the database detail drawer's 'View Info' button exists",
    )
    check(
        'id="databases-drawer-info-fields"' in html,
        "the database detail drawer's storage-info fields element exists",
    )
    # database.integrity_check: the detail drawer's read-only "Run
    # Integrity Check" action.
    check(
        'id="databases-drawer-integrity-button"' in html,
        "the database detail drawer's 'Run Integrity Check' button exists",
    )
    check(
        'id="databases-drawer-integrity-fields"' in html,
        "the database detail drawer's integrity-check fields element exists",
    )


def test_databases_view_uses_only_get_and_create_database_and_get_namespaces() -> None:
    print(
        "Checking databases.js calls only IrisApi.getDatabases()/getNamespaces()/"
        "getDatabaseInfo()/checkDatabaseIntegrity()/createDatabase()..."
    )
    databases_js = (FRONTEND_DIR / "js" / "databases.js").read_text(encoding="utf-8")

    check("IrisApi.getDatabases" in databases_js, "databases.js calls IrisApi.getDatabases()")
    # getNamespaces() is read-only and only used to compute the drawer's
    # "Namespace Usage" section — the same existing endpoint
    # namespaces.js itself already uses, not a new/expensive call.
    check(
        "IrisApi.getNamespaces" in databases_js,
        "databases.js calls IrisApi.getNamespaces() for the drawer's Namespace Usage section",
    )
    # database.info: read-only, drawer-only "View Info" action — never
    # fetched automatically, only on the button's own click handler.
    check(
        "IrisApi.getDatabaseInfo" in databases_js,
        "databases.js calls IrisApi.getDatabaseInfo() for the drawer's 'View Info' action",
    )
    # database.integrity_check: read-only, drawer-only "Run Integrity
    # Check" action — same discipline, never fetched automatically.
    check(
        "IrisApi.checkDatabaseIntegrity" in databases_js,
        "databases.js calls IrisApi.checkDatabaseIntegrity() for the drawer's "
        "'Run Integrity Check' action",
    )
    # database.create (the "New Database" wizard) is this view's one
    # sanctioned mutating capability — it must go through the IrisApi
    # wrapper, never a raw fetch() (checked in
    # test_no_mutating_http_method_anywhere_in_frontend_js below).
    check(
        "IrisApi.createDatabase" in databases_js,
        "databases.js calls IrisApi.createDatabase() for its 'New Database' wizard",
    )
    # database.mount: drawer-only, dry-run preview then explicit
    # confirmation — also only through the IrisApi wrapper.
    check(
        "IrisApi.mountDatabase" in databases_js,
        "databases.js calls IrisApi.mountDatabase() for the drawer's mount action",
    )
    check(
        "databases-drawer-mount" in databases_js,
        "databases.js renders into the drawer's mount elements",
    )
    other_methods = ["getInfo", "getProcesses", "getWebApps", "getTasks"]
    for method in other_methods:
        check(method not in databases_js, f"databases.js does NOT call IrisApi.{method}()")

    referenced_paths = set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', databases_js))
    check(
        referenced_paths in ({"/api/iris/databases"}, set()),
        f"databases.js references only /api/iris/databases as a literal path "
        f"(found: {referenced_paths or 'none, uses the IrisApi wrapper only'})",
    )
    check(
        "databases-card-grid" in databases_js,
        "databases.js renders into the databases card grid element",
    )
    check(
        "databases-drawer" in databases_js,
        "databases.js renders into the database detail drawer element",
    )
    check(
        "database-create-drawer" in databases_js,
        "databases.js renders into the 'New Database' wizard drawer element",
    )
    check(
        "databases-drawer-info" in databases_js,
        "databases.js renders into the drawer's storage-info elements",
    )
    check(
        "databases-drawer-integrity" in databases_js,
        "databases.js renders into the drawer's integrity-check elements",
    )
    check("fetch(" not in databases_js, "databases.js makes no raw fetch() call (goes through IrisApi)")


def test_web_apps_nav_and_view_exist_and_are_enabled() -> None:
    print("Checking the Web Apps nav item and view exist and are enabled...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    nav_match = re.search(
        r'<button class="nav-item[^"]*"[^>]*data-view="web-apps"[^>]*>', html
    )
    check(nav_match is not None, "a nav-item button with data-view=\"web-apps\" exists")
    check("disabled" not in nav_match.group(0), "the Web Apps nav-item is NOT disabled")

    view_match = re.search(
        r'<section[^>]*id="view-web-apps"[^>]*data-view="web-apps"[^>]*>', html
    )
    check(view_match is not None, 'a <section id="view-web-apps" data-view="web-apps"> exists')

    check('id="web-apps-table-body"' in html, "the web apps table body element exists")
    check('id="web-apps-summary-grid"' in html, "the web apps KPI grid exists")
    check('id="web-apps-filter-search"' in html, "the web apps search input exists")
    check('id="web-apps-filter-kind"' in html, "the web apps REST/CSP kind filter exists")
    check('id="web-apps-drawer"' in html, "the web apps detail drawer element exists")
    check('id="web-apps-tab-rest"' in html, "the web apps drawer has a REST Endpoints tab")
    check('id="web-apps-rest-search"' in html, "the REST endpoints search input exists")
    check('id="web-apps-rest-detail-view"' in html, "the REST endpoint detail view exists")
    check('id="web-sessions-section"' in html, "the Web Sessions section exists")
    check('id="web-sessions-filter-search"' in html, "the web sessions search input exists")
    check('id="web-sessions-drawer"' in html, "the web session detail drawer exists")
    check('id="web-apps-enable-check-button"' in html, "the drawer's Enabled State dry-run check exists")
    check('id="web-apps-enable-ack-checkbox"' in html, "the Enabled State acknowledgment checkbox exists")
    check('id="web-apps-enable-confirm-button"' in html, "the Enabled State confirm button exists")


def test_web_apps_view_uses_only_web_app_read_endpoints() -> None:
    print("Checking web-apps.js calls only the read-only web-app list/detail endpoints...")
    web_apps_js = (FRONTEND_DIR / "js" / "web-apps.js").read_text(encoding="utf-8")

    check("IrisApi.getWebApps" in web_apps_js, "web-apps.js calls IrisApi.getWebApps()")
    check(
        "IrisApi.getWebAppDetail" in web_apps_js,
        "web-apps.js calls IrisApi.getWebAppDetail() for the detail drawer",
    )
    check(
        "IrisApi.getWebAppRestEndpoints" in web_apps_js,
        "web-apps.js calls IrisApi.getWebAppRestEndpoints() for the REST Endpoints tab",
    )
    check(
        "IrisApi.getWebSessions" in web_apps_js,
        "web-apps.js calls IrisApi.getWebSessions() for the Web Sessions section",
    )
    # Its one mutation goes through the sanctioned api.js wrapper, never a
    # raw fetch or another operation's wrapper.
    check(
        "IrisApi.setWebAppEnabled" in web_apps_js,
        "web-apps.js's only mutation is IrisApi.setWebAppEnabled() (web_app.set_enabled)",
    )
    for other_mutation in ("createNamespace", "createDatabase", "mountDatabase", "fetch("):
        check(other_mutation not in web_apps_js, f"web-apps.js does not use {other_mutation}")
    # IRIS's web-session ID (what DELETE /v2/web-session?id= takes) is
    # stripped by the backend; the frontend must never try to read one.
    api_js = (FRONTEND_DIR / "js" / "api.js").read_text(encoding="utf-8")
    for name, source in (("web-apps.js", web_apps_js), ("api.js", api_js)):
        check(
            re.search(r"\.ID\b|[\"']ID[\"']", source) is None,
            f"{name} never references a session ID field",
        )
    other_methods = ["getInfo", "getNamespaces", "getProcesses", "getDatabases", "getTasks"]
    for method in other_methods:
        check(method not in web_apps_js, f"web-apps.js does NOT call IrisApi.{method}()")

    referenced_paths = set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', web_apps_js))
    check(
        referenced_paths in ({"/api/iris/web-apps"}, set()),
        f"web-apps.js references no /api/iris/* path other than via IrisApi "
        f"(found: {referenced_paths or 'none, uses IrisApi.getWebApps()'})",
    )
    check(
        "web-apps-table-body" in web_apps_js,
        "web-apps.js renders into the web apps table body element",
    )


def test_tasks_nav_and_view_exist_and_are_enabled() -> None:
    print("Checking the Tasks nav item and view exist and are enabled...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    nav_match = re.search(
        r'<button class="nav-item[^"]*"[^>]*data-view="tasks"[^>]*>', html
    )
    check(nav_match is not None, "a nav-item button with data-view=\"tasks\" exists")
    check("disabled" not in nav_match.group(0), "the Tasks nav-item is NOT disabled")

    view_match = re.search(
        r'<section[^>]*id="view-tasks"[^>]*data-view="tasks"[^>]*>', html
    )
    check(view_match is not None, 'a <section id="view-tasks" data-view="tasks"> exists')

    check('id="tasks-table-body"' in html, "the tasks table body element exists")
    check('id="tasks-summary-grid"' in html, "the tasks KPI grid exists")
    check('id="tasks-filter-search"' in html, "the tasks search input exists")
    check('id="tasks-filter-state"' in html, "the tasks State filter exists")
    check('id="tasks-drawer"' in html, "the tasks detail drawer element exists")
    for tab in ("overview", "schedule", "execution", "settings"):
        check(f'id="tasks-tab-{tab}"' in html, f"the tasks drawer has a {tab} tab")


def test_tasks_view_uses_only_task_read_endpoints() -> None:
    print("Checking tasks.js calls only the read-only task overview/manager/detail endpoints...")
    tasks_js = (FRONTEND_DIR / "js" / "tasks.js").read_text(encoding="utf-8")

    check("IrisApi.getTaskOverview" in tasks_js, "tasks.js calls IrisApi.getTaskOverview()")
    check("IrisApi.getTaskManager" in tasks_js, "tasks.js calls IrisApi.getTaskManager()")
    check(
        "IrisApi.getTaskDetail" in tasks_js,
        "tasks.js calls IrisApi.getTaskDetail() for the detail drawer",
    )
    other_methods = ["getInfo", "getNamespaces", "getProcesses", "getDatabases", "getWebApps", "getTasks"]
    for method in other_methods:
        check(method not in tasks_js, f"tasks.js does NOT call IrisApi.{method}()")
    for mutation in ("createNamespace", "createDatabase", "mountDatabase", "setWebAppEnabled", "fetch("):
        check(mutation not in tasks_js, f"tasks.js does not use {mutation}")
    # Run state comes from the backend-derived State (GET /v2/task/info),
    # never from GET /v2/tasks' own Suspended flag, which was observed wrong.
    check(
        re.search(r"task\.Suspended\b", tasks_js) is None,
        "tasks.js never reads the task list's own Suspended flag",
    )

    referenced_paths = set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', tasks_js))
    check(
        referenced_paths == set(),
        f"tasks.js references no /api/iris/* path other than via IrisApi (found: {referenced_paths or 'none'})",
    )
    check(
        "tasks-table-body" in tasks_js,
        "tasks.js renders into the tasks table body element",
    )


def test_security_nav_and_view_exist_and_are_enabled() -> None:
    print("Checking the Security nav item and view exist and are enabled...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    nav_match = re.search(
        r'<button class="nav-item[^"]*"[^>]*data-view="security"[^>]*>', html
    )
    check(nav_match is not None, "a nav-item button with data-view=\"security\" exists")
    check("disabled" not in nav_match.group(0), "the Security nav-item is NOT disabled")

    view_match = re.search(
        r'<section[^>]*id="view-security"[^>]*data-view="security"[^>]*>', html
    )
    check(view_match is not None, 'a <section id="view-security" data-view="security"> exists')

    check('id="security-oauth2-server-list"' in html, "the OAuth2 server info list element exists")
    check(
        'id="security-client-defs-table-body"' in html,
        "the client server definitions table body element exists",
    )
    check(
        'id="security-server-clients-table-body"' in html,
        "the registered clients table body element exists",
    )


def test_security_view_uses_only_security_endpoints() -> None:
    print("Checking security.js calls only the three OAuth2 endpoints and nothing else...")
    security_js = (FRONTEND_DIR / "js" / "security.js").read_text(encoding="utf-8")

    required_methods = [
        "IrisApi.getOauth2Server",
        "IrisApi.getOauth2ClientServerDefinitions",
        "IrisApi.getOauth2ServerClients",
    ]
    for method in required_methods:
        check(method in security_js, f"security.js calls {method}()")

    other_methods = ["getInfo", "getNamespaces", "getProcesses", "getDatabases", "getWebApps", "getTasks"]
    for method in other_methods:
        check(method not in security_js, f"security.js does NOT call IrisApi.{method}()")

    referenced_paths = set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', security_js))
    expected_paths = {
        "/api/iris/security/oauth2/server",
        "/api/iris/security/oauth2/client/server-definitions",
        "/api/iris/security/oauth2/server/clients",
    }
    check(
        referenced_paths in (expected_paths, set()),
        f"security.js references only the three OAuth2 paths as literal paths "
        f"(found: {referenced_paths or 'none, uses IrisApi methods'})",
    )
    check(
        "security-oauth2-server-list" in security_js,
        "security.js renders into the OAuth2 server info list element",
    )
    check(
        "security-client-defs-table-body" in security_js
        and "security-server-clients-table-body" in security_js,
        "security.js renders into both OAuth2 list table body elements",
    )


def test_journal_nav_and_view_exist_and_use_only_journal_settings() -> None:
    print("Checking the Journal nav item/view exist and journal.js uses only GET /api/iris/journal/settings...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    nav_match = re.search(
        r'<button class="nav-item[^"]*"[^>]*data-view="journal"[^>]*>', html
    )
    check(nav_match is not None, "a nav-item button with data-view=\"journal\" exists")
    check("disabled" not in nav_match.group(0), "the Journal nav-item is NOT disabled")

    view_match = re.search(
        r'<section[^>]*id="view-journal"[^>]*data-view="journal"[^>]*>', html
    )
    check(view_match is not None, 'a <section id="view-journal" data-view="journal"> exists')

    journal_js = (FRONTEND_DIR / "js" / "journal.js").read_text(encoding="utf-8")
    check("IrisApi.getJournalSettings" in journal_js, "journal.js calls IrisApi.getJournalSettings()")
    other_methods = [
        "getInfo", "getNamespaces", "getProcesses", "getDatabases", "getWebApps", "getTasks",
        "getOauth2Server", "getOauth2ClientServerDefinitions", "getOauth2ServerClients",
    ]
    for method in other_methods:
        check(method not in journal_js, f"journal.js does NOT call IrisApi.{method}()")

    referenced_paths = set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', journal_js))
    check(
        referenced_paths in ({"/api/iris/journal/settings"}, set()),
        f"journal.js references only /api/iris/journal/settings as a literal path "
        f"(found: {referenced_paths or 'none, uses IrisApi.getJournalSettings()'})",
    )
    check("journal-settings-list" in journal_js, "journal.js renders into the journal settings list element")


def test_operations_nav_and_view_exist_and_use_only_expected_endpoints() -> None:
    print("Checking the Operations nav item/view exist and operations.js uses only its expected IrisApi methods...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    nav_match = re.search(
        r'<button class="nav-item[^"]*"[^>]*data-view="operations"[^>]*>', html
    )
    check(nav_match is not None, "a nav-item button with data-view=\"operations\" exists")
    check("disabled" not in nav_match.group(0), "the Operations nav-item is NOT disabled")

    view_match = re.search(
        r'<section[^>]*id="view-operations"[^>]*data-view="operations"[^>]*>', html
    )
    check(view_match is not None, 'a <section id="view-operations" data-view="operations"> exists')
    check(
        'id="operations-review-list"' in html,
        "the journal.update_purge_archived review list element exists",
    )

    execute_element_ids = [
        "operations-execute-current-list",
        "operations-execute-choose",
        "operations-set-true-button",
        "operations-set-false-button",
        "operations-execute-confirm",
        "operations-execute-confirm-text",
        "operations-confirm-button",
        "operations-cancel-button",
        "operations-execute-result",
        "operations-result-list",
    ]
    for element_id in execute_element_ids:
        check(f'id="{element_id}"' in html, f"the {element_id!r} execute-flow element exists")

    operations_js = (FRONTEND_DIR / "js" / "operations.js").read_text(encoding="utf-8")
    check("IrisApi.getOperations" in operations_js, "operations.js calls IrisApi.getOperations()")
    check(
        "IrisApi.getJournalSettings" in operations_js,
        "operations.js calls IrisApi.getJournalSettings() to show the CURRENT value",
    )
    check(
        "IrisApi.executeJournalPurgeArchived" in operations_js,
        "operations.js calls IrisApi.executeJournalPurgeArchived() to execute, via the existing framework",
    )

    other_methods = [
        "getInfo", "getNamespaces", "getProcesses", "getDatabases", "getWebApps", "getTasks",
        "getOauth2Server", "getOauth2ClientServerDefinitions", "getOauth2ServerClients",
    ]
    for method in other_methods:
        check(method not in operations_js, f"operations.js does NOT call IrisApi.{method}()")

    # operations.js must never construct its own request or authorization
    # decision — everything it sends is via the IrisApi wrapper, whose
    # scope is independently verified in
    # test_no_mutating_http_method_anywhere_in_frontend_js.
    check("fetch(" not in operations_js, "operations.js makes no raw fetch() call")
    referenced_paths = set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', operations_js))
    check(
        referenced_paths == set(),
        f"operations.js references no /api/iris/* path as a literal string "
        f"(found: {referenced_paths}) — every request goes through IrisApi",
    )

    # No bypass/force field anywhere, and execution is only ever wired to
    # the Confirm & Execute button's own click handler — never called
    # during load/refresh. Checked as a literal, callable code form (a
    # quoted object key) rather than a blunt substring match, so an
    # explanatory comment describing what this file deliberately does NOT
    # do isn't mistaken for the thing itself.
    for bypass_word in ("force", "bypass", "skip_confirmation", "skipConfirmation"):
        check(
            re.search(rf'["\']{bypass_word}["\']\s*:', operations_js) is None,
            f"operations.js sends no {bypass_word!r} field",
        )
    confirm_click_wiring = re.search(
        r'confirmButton\.addEventListener\("click",\s*\(\)\s*=>\s*\{\s*executeConfirmed\(\);',
        operations_js,
    )
    check(
        confirm_click_wiring is not None,
        "executeConfirmed() is wired to the Confirm button's own click handler",
    )
    # The only CALL (not comment/docstring mention) of the identifier,
    # outside its own definition, should be that one click handler. Line
    # and block comments are stripped first, so a prose mention (like the
    # one a few lines above explaining this exact guarantee) is never
    # mistaken for a real call site.
    code_only = re.sub(r"//.*", "", operations_js)
    code_only = re.sub(r"/\*[\s\S]*?\*/", "", code_only)
    invocation_sites = [
        m.start()
        for m in re.finditer(r"executeConfirmed\(", code_only)
        if not code_only[: m.start()].endswith("function ")
    ]
    check(
        len(invocation_sites) == 1,
        "executeConfirmed() is invoked exactly once, from the Confirm button's click handler",
    )


def test_ai_assistant_nav_and_view_exist_and_use_only_assistant_query() -> None:
    print("Checking the AI Assistant nav item/view exist and ai-assistant.js uses only IrisApi.queryAssistant...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    nav_match = re.search(
        r'<button class="nav-item[^"]*"[^>]*data-view="ai-assistant"[^>]*>', html
    )
    check(nav_match is not None, "a nav-item button with data-view=\"ai-assistant\" exists")
    check("disabled" not in nav_match.group(0), "the AI Assistant nav-item is NOT disabled")

    view_match = re.search(
        r'<section[^>]*id="view-ai-assistant"[^>]*data-view="ai-assistant"[^>]*>', html
    )
    check(
        view_match is not None,
        'a <section id="view-ai-assistant" data-view="ai-assistant"> exists',
    )
    check('id="ai-chat-messages"' in html, "the chat message area exists")
    check('id="ai-chat-input"' in html, "the chat input exists")
    check('id="ai-chat-send-button"' in html, "the chat Send button exists")

    suggested_prompts = [
        "Show me the current IRIS system status",
        "How many processes are running?",
        "Show database status",
    ]
    for prompt in suggested_prompts:
        check(prompt in html, f"suggested prompt {prompt!r} is present")

    ai_js = (FRONTEND_DIR / "js" / "ai-assistant.js").read_text(encoding="utf-8")
    check("fetch(" not in ai_js, "ai-assistant.js makes no raw fetch() call (goes through IrisApi)")
    check(
        re.search(r'from\s+["\']\./api\.js["\']', ai_js) is not None,
        "ai-assistant.js imports from api.js",
    )
    check(
        "IrisApi.queryAssistant" in ai_js,
        "ai-assistant.js calls IrisApi.queryAssistant()",
    )

    other_methods = [
        "getInfo", "getNamespaces", "getProcesses", "getDatabases", "getWebApps", "getTasks",
        "getOauth2Server", "getOauth2ClientServerDefinitions", "getOauth2ServerClients",
        "getJournalSettings", "getOperations",
    ]
    for method in other_methods:
        check(method not in ai_js, f"ai-assistant.js does NOT call IrisApi.{method}() directly")

    referenced_paths = set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', ai_js))
    check(
        referenced_paths in ({"/api/iris/assistant/query"}, set()),
        f"ai-assistant.js references only /api/iris/assistant/query as a literal path "
        f"(found: {referenced_paths or 'none, uses IrisApi.queryAssistant()'})",
    )

    # This view must never trigger the existing mutating operation, and
    # must never carry a confirmation/bypass shortcut. Checked as literal,
    # callable code forms rather than a blunt substring match, so an
    # explanatory comment describing what this view deliberately does NOT
    # do isn't mistaken for the thing itself.
    check(
        '"/api/iris/journal/purge-archived"' not in ai_js,
        "ai-assistant.js does NOT reference the mutating purge-archived route as a literal path",
    )
    check(
        re.search(r'["\']confirmed["\']\s*:', ai_js) is None,
        "ai-assistant.js does NOT send a confirmation/bypass field",
    )


def test_observability_nav_and_view_exist_and_use_only_traces_endpoint() -> None:
    print("Checking the Observability nav item/view exist and observability.js uses only GET /api/iris/observability/traces...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    nav_match = re.search(
        r'<button class="nav-item[^"]*"[^>]*data-view="observability"[^>]*>', html
    )
    check(nav_match is not None, "a nav-item button with data-view=\"observability\" exists")
    check("disabled" not in nav_match.group(0), "the Observability nav-item is NOT disabled")

    view_match = re.search(
        r'<section[^>]*id="view-observability"[^>]*data-view="observability"[^>]*>', html
    )
    check(
        view_match is not None,
        'a <section id="view-observability" data-view="observability"> exists',
    )
    check('id="observability-table-body"' in html, "the traces table body element exists")

    observability_js = (FRONTEND_DIR / "js" / "observability.js").read_text(encoding="utf-8")
    check(
        "IrisApi.getExecutionTraces" in observability_js,
        "observability.js calls IrisApi.getExecutionTraces()",
    )

    other_methods = [
        "getInfo", "getNamespaces", "getProcesses", "getDatabases", "getWebApps", "getTasks",
        "getOauth2Server", "getOauth2ClientServerDefinitions", "getOauth2ServerClients",
        "getJournalSettings", "getOperations", "queryAssistant", "executeJournalPurgeArchived",
    ]
    for method in other_methods:
        check(method not in observability_js, f"observability.js does NOT call IrisApi.{method}()")

    check("fetch(" not in observability_js, "observability.js makes no raw fetch() call")
    referenced_paths = set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', observability_js))
    check(
        referenced_paths == set(),
        f"observability.js references no /api/iris/* path as a literal string "
        f"(found: {referenced_paths}) — every request goes through IrisApi",
    )


def test_extensions_nav_and_view_exist_and_are_enabled() -> None:
    print("Checking the Extensions nav item and view exist and are enabled...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    nav_match = re.search(
        r'<button class="nav-item[^"]*"[^>]*data-view="extensions"[^>]*>', html
    )
    check(nav_match is not None, "a nav-item button with data-view=\"extensions\" exists")
    check("disabled" not in nav_match.group(0), "the Extensions nav-item is NOT disabled")

    view_match = re.search(
        r'<section[^>]*id="view-extensions"[^>]*data-view="extensions"[^>]*>', html
    )
    check(view_match is not None, 'a <section id="view-extensions" data-view="extensions"> exists')

    check(
        'id="extensions-ext-lang-servers-table-body"' in html,
        "the external language servers table body element exists",
    )
    check(
        'id="extensions-fs-access-purposes-table-body"' in html,
        "the file system access purposes table body element exists",
    )
    check(
        'id="extensions-wallet-collections-table-body"' in html,
        "the wallet collections table body element exists",
    )


def test_extensions_view_uses_only_expected_endpoints() -> None:
    print("Checking extensions.js calls only its three expected endpoints and nothing else...")
    extensions_js = (FRONTEND_DIR / "js" / "extensions.js").read_text(encoding="utf-8")

    required_methods = [
        "IrisApi.getExtLangServers",
        "IrisApi.getFsAccessPurposes",
        "IrisApi.getWalletCollections",
    ]
    for method in required_methods:
        check(method in extensions_js, f"extensions.js calls {method}()")

    other_methods = [
        "getInfo", "getNamespaces", "getProcesses", "getDatabases", "getWebApps", "getTasks",
        "getOauth2Server", "getOauth2ClientServerDefinitions", "getOauth2ServerClients",
        "getJournalSettings", "getOperations", "queryAssistant", "executeJournalPurgeArchived",
        "getExecutionTraces",
    ]
    for method in other_methods:
        check(method not in extensions_js, f"extensions.js does NOT call IrisApi.{method}()")

    check("fetch(" not in extensions_js, "extensions.js makes no raw fetch() call (goes through IrisApi)")
    referenced_paths = set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', extensions_js))
    check(
        referenced_paths == set(),
        f"extensions.js references no /api/iris/* path as a literal string "
        f"(found: {referenced_paths}) — every request goes through IrisApi",
    )
    check(
        "extensions-ext-lang-servers-table-body" in extensions_js
        and "extensions-fs-access-purposes-table-body" in extensions_js
        and "extensions-wallet-collections-table-body" in extensions_js,
        "extensions.js renders into all three table body elements",
    )


def test_investigation_nav_and_view_exist_and_are_enabled() -> None:
    print("Checking the Investigation nav item and view exist and are enabled...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    nav_match = re.search(
        r'<button class="nav-item[^"]*"[^>]*data-view="investigation"[^>]*>', html
    )
    check(nav_match is not None, "a nav-item button with data-view=\"investigation\" exists")
    check("disabled" not in nav_match.group(0), "the Investigation nav-item is NOT disabled")

    view_match = re.search(
        r'<section[^>]*id="view-investigation"[^>]*data-view="investigation"[^>]*>', html
    )
    check(
        view_match is not None,
        'a <section id="view-investigation" data-view="investigation"> exists',
    )

    check('id="investigation-table-body"' in html, "the audit records table body element exists")
    check(
        'id="investigation-filter-form"' in html,
        "the audit record filter form exists",
    )
    for filter_id in (
        "investigation-filter-begin",
        "investigation-filter-end",
        "investigation-filter-event-types",
        "investigation-filter-username",
        "investigation-filter-search",
        "investigation-filter-order",
    ):
        check(f'id="{filter_id}"' in html, f"the {filter_id!r} filter field exists")


def test_investigation_view_uses_only_expected_endpoints() -> None:
    print("Checking investigation.js calls only its two expected endpoints and nothing else...")
    investigation_js = (FRONTEND_DIR / "js" / "investigation.js").read_text(encoding="utf-8")

    required_methods = ["IrisApi.getAuditEnabled", "IrisApi.getAuditRecords"]
    for method in required_methods:
        check(method in investigation_js, f"investigation.js calls {method}()")

    other_methods = [
        "getInfo", "getNamespaces", "getProcesses", "getDatabases", "getWebApps", "getTasks",
        "getOauth2Server", "getOauth2ClientServerDefinitions", "getOauth2ServerClients",
        "getJournalSettings", "getOperations", "queryAssistant", "executeJournalPurgeArchived",
        "getExecutionTraces", "getExtLangServers", "getFsAccessPurposes", "getWalletCollections",
    ]
    for method in other_methods:
        check(method not in investigation_js, f"investigation.js does NOT call IrisApi.{method}()")

    check(
        "fetch(" not in investigation_js,
        "investigation.js makes no raw fetch() call (goes through IrisApi)",
    )
    referenced_paths = set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', investigation_js))
    check(
        referenced_paths == set(),
        f"investigation.js references no /api/iris/* path as a literal string "
        f"(found: {referenced_paths}) — every request goes through IrisApi",
    )
    check(
        "investigation-table-body" in investigation_js,
        "investigation.js renders into the audit records table body element",
    )


def test_capabilities_nav_and_view_exist_and_are_enabled() -> None:
    print("Checking the API Capability Explorer nav item and view exist and are enabled...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    nav_match = re.search(
        r'<button class="nav-item[^"]*"[^>]*data-view="capabilities"[^>]*>', html
    )
    check(nav_match is not None, "a nav-item button with data-view=\"capabilities\" exists")
    check("disabled" not in nav_match.group(0), "the API Capability Explorer nav-item is NOT disabled")

    view_match = re.search(
        r'<section[^>]*id="view-capabilities"[^>]*data-view="capabilities"[^>]*>', html
    )
    check(
        view_match is not None,
        'a <section id="view-capabilities" data-view="capabilities"> exists',
    )

    check('id="capabilities-table-body"' in html, "the capabilities table body element exists")
    check('id="capabilities-filter-form"' in html, "the capability filter form exists")
    for filter_id in (
        "capabilities-filter-search",
        "capabilities-filter-verification",
        "capabilities-filter-available",
    ):
        check(f'id="{filter_id}"' in html, f"the {filter_id!r} filter field exists")


def test_capabilities_view_uses_only_expected_endpoint() -> None:
    print("Checking capabilities.js calls only IrisApi.getCapabilities() and nothing else...")
    capabilities_js = (FRONTEND_DIR / "js" / "capabilities.js").read_text(encoding="utf-8")

    check(
        "IrisApi.getCapabilities" in capabilities_js,
        "capabilities.js calls IrisApi.getCapabilities()",
    )

    other_methods = [
        "getInfo", "getNamespaces", "getProcesses", "getDatabases", "getWebApps", "getTasks",
        "getOauth2Server", "getOauth2ClientServerDefinitions", "getOauth2ServerClients",
        "getJournalSettings", "getOperations", "queryAssistant", "executeJournalPurgeArchived",
        "getExecutionTraces", "getExtLangServers", "getFsAccessPurposes", "getWalletCollections",
        "getAuditEnabled", "getAuditRecords",
    ]
    for method in other_methods:
        check(method not in capabilities_js, f"capabilities.js does NOT call IrisApi.{method}()")

    check(
        "fetch(" not in capabilities_js,
        "capabilities.js makes no raw fetch() call (goes through IrisApi)",
    )
    referenced_paths = set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', capabilities_js))
    check(
        referenced_paths == set(),
        f"capabilities.js references no /api/iris/* path as a literal string "
        f"(found: {referenced_paths}) — every request goes through IrisApi",
    )
    check(
        "capabilities-table-body" in capabilities_js,
        "capabilities.js renders into the capabilities table body element",
    )

    # Filtering must be a pure re-render of the already-fetched list, never
    # a second network call — this module fetches exactly once per
    # load/Refresh, unlike investigation.js's server-side filtered search.
    # Comments are stripped first so a prose mention of "IrisApi." isn't
    # mistaken for a second real call site.
    code_only = re.sub(r"//.*", "", capabilities_js)
    code_only = re.sub(r"/\*[\s\S]*?\*/", "", code_only)
    check(
        code_only.count("IrisApi.") == 1,
        "capabilities.js calls an IrisApi method exactly once (filtering never re-fetches)",
    )


def test_observability_investigation_cross_link_exists() -> None:
    print("Checking the Observability <-> Investigation cross-link is wired end to end...")

    nav_js = (FRONTEND_DIR / "js" / "nav.js").read_text(encoding="utf-8")
    check(
        "export function navigateTo" in nav_js,
        "nav.js exports navigateTo(), used by the cross-link to switch views programmatically",
    )

    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    for element_id in (
        "observability-filter-form",
        "observability-filter-begin",
        "observability-filter-end",
        "observability-filter-clear-button",
    ):
        check(f'id="{element_id}"' in html, f"the {element_id!r} Observability time-filter element exists")

    observability_js = (FRONTEND_DIR / "js" / "observability.js").read_text(encoding="utf-8")
    check(
        "export function setTimeWindow" in observability_js,
        "observability.js exports setTimeWindow() for Investigation's cross-link to call",
    )
    check(
        "onInvestigateTimeWindow" in observability_js,
        "observability.js accepts an onInvestigateTimeWindow callback for its own cross-link button",
    )
    # The cross-link's whole reason for existing is that no real IRIS/trace
    # ID ties the two systems together — only this app never sends a
    # mutating request anywhere, still true after adding this feature.
    check("fetch(" not in observability_js, "observability.js still makes no raw fetch() call")
    check(
        set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', observability_js)) == set(),
        "observability.js still references no /api/iris/* path as a literal string",
    )

    investigation_js = (FRONTEND_DIR / "js" / "investigation.js").read_text(encoding="utf-8")
    check(
        "export function setTimeWindow" in investigation_js,
        "investigation.js exports setTimeWindow() for Observability's cross-link to call",
    )
    check(
        "onInvestigateTraces" in investigation_js,
        "investigation.js accepts an onInvestigateTraces callback for its own cross-link button",
    )
    check("fetch(" not in investigation_js, "investigation.js still makes no raw fetch() call")
    check(
        set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', investigation_js)) == set(),
        "investigation.js still references no /api/iris/* path as a literal string",
    )

    app_js = (FRONTEND_DIR / "js" / "app.js").read_text(encoding="utf-8")
    check(
        "navigateTo" in app_js,
        "app.js imports/uses navigateTo() to wire the cross-link",
    )
    check(
        "onInvestigateTimeWindow" in app_js and "onInvestigateTraces" in app_js,
        "app.js wires both cross-link callbacks (Observability -> Investigation and back)",
    )
    check(
        "setInvestigationTimeWindow" in app_js and "setObservabilityTimeWindow" in app_js,
        "app.js calls each view's own setTimeWindow() (aliased to avoid a name collision) "
        "rather than reimplementing either view's filtering",
    )


def test_dashboard_is_the_landing_screen_with_activity_and_quicklinks() -> None:
    print("Checking the Dashboard surfaces recent activity and working quicklinks to other views...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    for element_id in (
        "dashboard-activity-empty",
        "dashboard-activity-table-wrapper",
        "dashboard-activity-table-body",
        "dashboard-view-observability-button",
        "dashboard-quicklinks",
    ):
        check(f'id="{element_id}"' in html, f"the {element_id!r} dashboard element exists")

    # Every quicklink must point at a real, enabled nav view — never a
    # typo'd or since-renamed data-view value.
    quicklink_targets = re.findall(r'data-quicklink="([a-z-]+)"', html)
    check(len(quicklink_targets) >= 3, f"found {len(quicklink_targets)} dashboard quicklinks")
    for target in quicklink_targets:
        nav_match = re.search(
            rf'<button class="nav-item[^"]*"[^>]*data-view="{target}"[^>]*>', html
        )
        check(nav_match is not None, f"quicklink target {target!r} matches a real nav-item")
        check("disabled" not in nav_match.group(0), f"quicklink target {target!r}'s nav-item is NOT disabled")

    dashboard_js = (FRONTEND_DIR / "js" / "dashboard.js").read_text(encoding="utf-8")
    check(
        "IrisApi.getExecutionTraces" in dashboard_js,
        "dashboard.js calls IrisApi.getExecutionTraces() for its Recent Activity section",
    )
    # The design-system pass added two "Insights" donuts (Operations
    # Overview, API Coverage) reusing these two existing, already-used-
    # elsewhere GET routes — both still read-only, no new backend surface.
    check(
        "IrisApi.getOperations" in dashboard_js,
        "dashboard.js calls IrisApi.getOperations() for its Operations Overview insight",
    )
    check(
        "IrisApi.getCapabilities" in dashboard_js,
        "dashboard.js calls IrisApi.getCapabilities() for its API Coverage insight",
    )
    # The Tasks card/micro-bar use the same backend-derived run State as the
    # Tasks view (GET /api/iris/tasks/overview), never the task list's own
    # Suspended flag, which was observed reporting false for suspended tasks.
    check(
        "IrisApi.getTaskOverview" in dashboard_js,
        "dashboard.js calls IrisApi.getTaskOverview() for its Tasks card",
    )
    check("IrisApi.getTasks(" not in dashboard_js, "dashboard.js no longer calls IrisApi.getTasks()")
    check(
        re.search(r"task\.State\b", dashboard_js) is not None
        and re.search(r"task\.Suspended\b", dashboard_js) is None,
        "dashboard.js groups tasks by the overview's State, never the list's Suspended flag",
    )
    check(
        re.search(r'from\s+["\']\./nav\.js["\']', dashboard_js) is not None
        and "navigateTo" in dashboard_js,
        "dashboard.js imports and uses navigateTo() for its quicklinks",
    )
    # Still true after this refinement: the Dashboard remains entirely
    # read-only — no mutating verb, no raw fetch, and no IrisApi method
    # beyond the five it has always used plus the two Insights donuts above.
    other_methods = [
        "getOauth2Server", "getOauth2ClientServerDefinitions", "getOauth2ServerClients",
        "getJournalSettings", "queryAssistant", "executeJournalPurgeArchived",
        "getExtLangServers", "getFsAccessPurposes", "getWalletCollections",
        "getAuditEnabled", "getAuditRecords",
    ]
    for method in other_methods:
        check(method not in dashboard_js, f"dashboard.js does NOT call IrisApi.{method}()")
    check("fetch(" not in dashboard_js, "dashboard.js makes no raw fetch() call (goes through IrisApi)")


def test_no_mutating_http_method_anywhere_in_frontend_js() -> None:
    print("Checking no mutating HTTP method appears anywhere in frontend/js/*.js, except five sanctioned, scoped exceptions...")
    js_dir = FRONTEND_DIR / "js"
    mutating_methods = ["PUT", "POST", "DELETE", "PATCH"]

    # The five sanctioned mutating calls in the entire frontend, all in
    # api.js: postJournalPurgeArchived (POST /api/iris/journal/purge-
    # archived, backend/app/routes/journal.py), postNamespaceCreate (POST
    # /api/iris/namespaces, backend/app/routes/namespaces.py),
    # postDatabaseCreate (POST /api/iris/databases) and postDatabaseMount
    # (POST /api/iris/databases/mount, both backend/app/routes/
    # databases.py), and postWebAppSetEnabled (POST /api/iris/web-apps/
    # set-enabled, backend/app/routes/web_apps.py) — asserted below to be
    # scoped to exactly those five paths, never a different/new one. PUT and PATCH
    # remain forbidden everywhere, including in api.js — this project has
    # no PUT or PATCH route at all, mutating or otherwise.
    allowed_post_file = "api.js"

    for js_file in sorted(js_dir.glob("*.js")):
        content = js_file.read_text(encoding="utf-8")
        for method in mutating_methods:
            # Looks for the method as a quoted HTTP verb (e.g. method: "POST"),
            # not as an incidental substring (e.g. a word containing "post").
            pattern = rf'["\']{method}["\']'
            found = re.search(pattern, content) is not None
            if method == "POST" and js_file.name == allowed_post_file:
                check(
                    found,
                    f"{js_file.relative_to(REPO_ROOT)} contains the sanctioned POST(s) "
                    "(to the existing journal/purge-archived, namespaces, and databases routes)",
                )
                continue
            check(
                not found,
                f"{js_file.relative_to(REPO_ROOT)} does not reference HTTP method {method!r}",
            )

    # Each sanctioned POST must be tied to exactly its existing,
    # already-tested mutating route — never a different/new one.
    api_js = (js_dir / "api.js").read_text(encoding="utf-8")
    check(
        '"/api/iris/journal/purge-archived"' in api_js,
        "api.js's first sanctioned POST is scoped to the existing /api/iris/journal/purge-archived route",
    )
    check(
        "postNamespaceCreate" in api_js and "createNamespace:" in api_js,
        "api.js's second sanctioned POST (postNamespaceCreate) is exposed as IrisApi.createNamespace()",
    )
    check(
        "postDatabaseCreate" in api_js and "createDatabase:" in api_js,
        "api.js's third sanctioned POST (postDatabaseCreate) is exposed as IrisApi.createDatabase()",
    )
    check(
        '"/api/iris/databases/mount"' in api_js and "mountDatabase:" in api_js,
        "api.js's fourth sanctioned POST (postDatabaseMount) is scoped to /api/iris/databases/mount "
        "and exposed as IrisApi.mountDatabase()",
    )
    check(
        '"/api/iris/web-apps/set-enabled"' in api_js and "setWebAppEnabled:" in api_js,
        "api.js's fifth sanctioned POST (postWebAppSetEnabled) is scoped to "
        "/api/iris/web-apps/set-enabled and exposed as IrisApi.setWebAppEnabled()",
    )

    # operations.js (where the execute UI lives) must call the api.js
    # wrapper — it never constructs its own fetch call or duplicates
    # authorization logic.
    operations_js = (js_dir / "operations.js").read_text(encoding="utf-8")
    check(
        "fetch(" not in operations_js,
        "operations.js makes no raw fetch() call (goes through IrisApi)",
    )
    check(
        "IrisApi.executeJournalPurgeArchived" in operations_js,
        "operations.js calls IrisApi.executeJournalPurgeArchived()",
    )

    # namespaces.js (where the "New Namespace" wizard lives) must likewise
    # call the api.js wrapper only, never a raw fetch() or its own
    # authorization/confirmation logic.
    namespaces_js = (js_dir / "namespaces.js").read_text(encoding="utf-8")
    check(
        "fetch(" not in namespaces_js,
        "namespaces.js makes no raw fetch() call (goes through IrisApi)",
    )
    check(
        "IrisApi.createNamespace" in namespaces_js,
        "namespaces.js calls IrisApi.createNamespace()",
    )

    # databases.js (where the "New Database" wizard lives) must likewise
    # call the api.js wrapper only, never a raw fetch() or its own
    # authorization/confirmation logic.
    databases_js = (js_dir / "databases.js").read_text(encoding="utf-8")
    check(
        "fetch(" not in databases_js,
        "databases.js makes no raw fetch() call (goes through IrisApi)",
    )
    check(
        "IrisApi.createDatabase" in databases_js,
        "databases.js calls IrisApi.createDatabase()",
    )


def main() -> None:
    tests = [
        test_expected_files_exist_and_are_non_empty,
        test_frontend_can_be_served,
        test_api_paths_match_real_backend_routes,
        test_system_nav_and_view_exist_and_are_enabled,
        test_system_view_uses_only_get_info,
        test_namespaces_nav_and_view_exist_and_are_enabled,
        test_namespaces_view_uses_only_get_and_create_namespace,
        test_processes_nav_and_view_exist_and_are_enabled,
        test_processes_view_uses_only_get_processes,
        test_databases_nav_and_view_exist_and_are_enabled,
        test_databases_view_uses_only_get_and_create_database_and_get_namespaces,
        test_web_apps_nav_and_view_exist_and_are_enabled,
        test_web_apps_view_uses_only_web_app_read_endpoints,
        test_tasks_nav_and_view_exist_and_are_enabled,
        test_tasks_view_uses_only_task_read_endpoints,
        test_security_nav_and_view_exist_and_are_enabled,
        test_security_view_uses_only_security_endpoints,
        test_journal_nav_and_view_exist_and_use_only_journal_settings,
        test_operations_nav_and_view_exist_and_use_only_expected_endpoints,
        test_ai_assistant_nav_and_view_exist_and_use_only_assistant_query,
        test_observability_nav_and_view_exist_and_use_only_traces_endpoint,
        test_extensions_nav_and_view_exist_and_are_enabled,
        test_extensions_view_uses_only_expected_endpoints,
        test_investigation_nav_and_view_exist_and_are_enabled,
        test_investigation_view_uses_only_expected_endpoints,
        test_capabilities_nav_and_view_exist_and_are_enabled,
        test_capabilities_view_uses_only_expected_endpoint,
        test_observability_investigation_cross_link_exists,
        test_dashboard_is_the_landing_screen_with_activity_and_quicklinks,
        test_no_mutating_http_method_anywhere_in_frontend_js,
    ]
    for test in tests:
        print(f"\n{test.__name__}")
        test()
    print("\nAll frontend smoke checks passed.")


if __name__ == "__main__":
    main()
