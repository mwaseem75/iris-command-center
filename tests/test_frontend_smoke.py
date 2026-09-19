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
11. (Step 5) web-apps.js calls GET /api/iris/web-apps and no other
    endpoint, and renders into the web apps table body.
12. (Step 6) The Tasks nav item and view exist in the markup and the nav
    item is enabled (not `disabled`).
13. (Step 6) tasks.js calls GET /api/iris/tasks and no other endpoint, and
    renders into the tasks table body.
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

    check('id="namespaces-table-body"' in html, "the namespaces table body element exists")


def test_namespaces_view_uses_only_get_namespaces() -> None:
    print("Checking namespaces.js calls GET /api/iris/namespaces and nothing else...")
    namespaces_js = (FRONTEND_DIR / "js" / "namespaces.js").read_text(encoding="utf-8")

    check("IrisApi.getNamespaces" in namespaces_js, "namespaces.js calls IrisApi.getNamespaces()")
    other_methods = ["getInfo", "getProcesses", "getDatabases", "getWebApps", "getTasks"]
    for method in other_methods:
        check(method not in namespaces_js, f"namespaces.js does NOT call IrisApi.{method}()")

    referenced_paths = set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', namespaces_js))
    check(
        referenced_paths in ({"/api/iris/namespaces"}, set()),
        f"namespaces.js references only /api/iris/namespaces as a literal path "
        f"(found: {referenced_paths or 'none, uses IrisApi.getNamespaces()'})",
    )
    check(
        "namespaces-table-body" in namespaces_js,
        "namespaces.js renders into the namespaces table body element",
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

    check('id="databases-table-body"' in html, "the databases table body element exists")


def test_databases_view_uses_only_get_databases() -> None:
    print("Checking databases.js calls GET /api/iris/databases and nothing else...")
    databases_js = (FRONTEND_DIR / "js" / "databases.js").read_text(encoding="utf-8")

    check("IrisApi.getDatabases" in databases_js, "databases.js calls IrisApi.getDatabases()")
    other_methods = ["getInfo", "getNamespaces", "getProcesses", "getWebApps", "getTasks"]
    for method in other_methods:
        check(method not in databases_js, f"databases.js does NOT call IrisApi.{method}()")

    referenced_paths = set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', databases_js))
    check(
        referenced_paths in ({"/api/iris/databases"}, set()),
        f"databases.js references only /api/iris/databases as a literal path "
        f"(found: {referenced_paths or 'none, uses IrisApi.getDatabases()'})",
    )
    check(
        "databases-table-body" in databases_js,
        "databases.js renders into the databases table body element",
    )


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


def test_web_apps_view_uses_only_get_web_apps() -> None:
    print("Checking web-apps.js calls GET /api/iris/web-apps and nothing else...")
    web_apps_js = (FRONTEND_DIR / "js" / "web-apps.js").read_text(encoding="utf-8")

    check("IrisApi.getWebApps" in web_apps_js, "web-apps.js calls IrisApi.getWebApps()")
    other_methods = ["getInfo", "getNamespaces", "getProcesses", "getDatabases", "getTasks"]
    for method in other_methods:
        check(method not in web_apps_js, f"web-apps.js does NOT call IrisApi.{method}()")

    referenced_paths = set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', web_apps_js))
    check(
        referenced_paths in ({"/api/iris/web-apps"}, set()),
        f"web-apps.js references only /api/iris/web-apps as a literal path "
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


def test_tasks_view_uses_only_get_tasks() -> None:
    print("Checking tasks.js calls GET /api/iris/tasks and nothing else...")
    tasks_js = (FRONTEND_DIR / "js" / "tasks.js").read_text(encoding="utf-8")

    check("IrisApi.getTasks" in tasks_js, "tasks.js calls IrisApi.getTasks()")
    other_methods = ["getInfo", "getNamespaces", "getProcesses", "getDatabases", "getWebApps"]
    for method in other_methods:
        check(method not in tasks_js, f"tasks.js does NOT call IrisApi.{method}()")

    referenced_paths = set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', tasks_js))
    check(
        referenced_paths in ({"/api/iris/tasks"}, set()),
        f"tasks.js references only /api/iris/tasks as a literal path "
        f"(found: {referenced_paths or 'none, uses IrisApi.getTasks()'})",
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


def test_no_mutating_http_method_anywhere_in_frontend_js() -> None:
    print("Checking no mutating HTTP method appears anywhere in frontend/js/*.js, except one sanctioned, scoped exception...")
    js_dir = FRONTEND_DIR / "js"
    mutating_methods = ["PUT", "POST", "DELETE", "PATCH"]

    # The ONLY sanctioned mutating call in the entire frontend:
    # api.js's postJournalPurgeArchived, which forwards to the existing,
    # already-tested POST /api/iris/journal/purge-archived route (see
    # backend/app/routes/journal.py) — asserted below to be scoped to
    # exactly that path, never a different/new one. PUT and PATCH remain
    # forbidden everywhere, including in api.js — this project has no PUT
    # or PATCH route at all, mutating or otherwise.
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
                    f"{js_file.relative_to(REPO_ROOT)} contains the one sanctioned POST "
                    "(to the existing journal/purge-archived route)",
                )
                continue
            check(
                not found,
                f"{js_file.relative_to(REPO_ROOT)} does not reference HTTP method {method!r}",
            )

    # The sanctioned POST must be tied to exactly the existing,
    # already-tested mutating route — never a different/new one.
    api_js = (js_dir / "api.js").read_text(encoding="utf-8")
    check(
        '"/api/iris/journal/purge-archived"' in api_js,
        "api.js's sanctioned POST is scoped to the existing /api/iris/journal/purge-archived route",
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


def main() -> None:
    tests = [
        test_expected_files_exist_and_are_non_empty,
        test_frontend_can_be_served,
        test_api_paths_match_real_backend_routes,
        test_system_nav_and_view_exist_and_are_enabled,
        test_system_view_uses_only_get_info,
        test_namespaces_nav_and_view_exist_and_are_enabled,
        test_namespaces_view_uses_only_get_namespaces,
        test_processes_nav_and_view_exist_and_are_enabled,
        test_processes_view_uses_only_get_processes,
        test_databases_nav_and_view_exist_and_are_enabled,
        test_databases_view_uses_only_get_databases,
        test_web_apps_nav_and_view_exist_and_are_enabled,
        test_web_apps_view_uses_only_get_web_apps,
        test_tasks_nav_and_view_exist_and_are_enabled,
        test_tasks_view_uses_only_get_tasks,
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
        test_no_mutating_http_method_anywhere_in_frontend_js,
    ]
    for test in tests:
        print(f"\n{test.__name__}")
        test()
    print("\nAll frontend smoke checks passed.")


if __name__ == "__main__":
    main()
