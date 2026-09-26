"""Frontend smoke tests (no JS test framework).

Run with the backend venv, since it imports the FastAPI app:
    backend/.venv/Scripts/python tests/test_frontend_smoke.py

What it checks:
- the frontend files exist and index.html can be served;
- every /api/iris/* path in api.js is a real backend route (compared with
  the app's OpenAPI schema);
- each page has its nav item and view, the nav item is enabled, and the
  page's JS only calls the IrisApi methods it's supposed to;
- the only mutating calls are the POST wrappers in api.js, each tied to
  its own route; no PUT/PATCH/DELETE anywhere;
- pages that mutate go through the api.js wrappers and only run an
  operation from the confirm button, never on load;
- Observability and Investigation link to each other by time window;
- the Dashboard's quicklinks point at real nav views.

It doesn't start IRIS or call any IRIS endpoint.
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
        FRONTEND_DIR / "js" / "security-access.js",
        FRONTEND_DIR / "js" / "security-auth.js",
        FRONTEND_DIR / "js" / "security-wallet.js",
        FRONTEND_DIR / "js" / "security-x509.js",
        FRONTEND_DIR / "js" / "journal.js",
        FRONTEND_DIR / "js" / "operations.js",
        FRONTEND_DIR / "js" / "ai-assistant.js",
        FRONTEND_DIR / "js" / "observability.js",
        FRONTEND_DIR / "js" / "extensions.js",
        FRONTEND_DIR / "js" / "investigation.js",
        FRONTEND_DIR / "js" / "capabilities.js",
        FRONTEND_DIR / "js" / "theme.js",
        FRONTEND_DIR / "js" / "demo-activity.js",
        FRONTEND_DIR / "js" / "detail-workspace.js",
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

    from app.main import app  # imports the real app; importing doesn't call IRIS

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

    # Namespaces page: card grid, database-sharing section and a detail drawer.
    check('id="namespaces-card-grid"' in html, "the namespaces card grid element exists")
    check('id="namespaces-topology"' in html, "the namespaces topology element exists")
    check('id="namespaces-drawer"' in html, "the namespaces detail drawer element exists")


def test_namespaces_view_uses_only_get_and_create_namespace() -> None:
    print("Checking namespaces.js calls only IrisApi.getNamespaces()/getDatabases()/createNamespace()...")
    namespaces_js = (FRONTEND_DIR / "js" / "namespaces.js").read_text(encoding="utf-8")

    check("IrisApi.getNamespaces" in namespaces_js, "namespaces.js calls IrisApi.getNamespaces()")
    # The New Namespace wizard gets its database list from the databases
    # API, not a hardcoded list.
    check(
        "IrisApi.getDatabases" in namespaces_js,
        "namespaces.js calls IrisApi.getDatabases() to populate the wizard's database selectors",
    )
    # namespace.create (New Namespace wizard) is this page's only mutation
    # and must go through the IrisApi wrapper.
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

    # Databases page: card grid and detail drawer, like Namespaces.
    check('id="databases-card-grid"' in html, "the databases card grid element exists")
    check('id="databases-drawer"' in html, "the databases detail drawer element exists")
    # The "+ New Database" button opens the wizard (database.create).
    nav_button_match = re.search(
        r'<button class="btn btn--primary" type="button" id="databases-create-button">', html
    )
    check(nav_button_match is not None, "the '+ New Database' button exists and is enabled")
    check(
        'id="database-create-drawer"' in html,
        "the 'New Database' wizard drawer element exists",
    )
    # database.info: the drawer's "View Info" action.
    check(
        'id="databases-drawer-info-button"' in html,
        "the database detail drawer's 'View Info' button exists",
    )
    check(
        'id="databases-drawer-info-fields"' in html,
        "the database detail drawer's storage-info fields element exists",
    )
    # database.integrity_check: the drawer's "Run Integrity Check" action.
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
    # getNamespaces() is only used for the drawer's "Namespace Usage"
    # section (same endpoint namespaces.js uses).
    check(
        "IrisApi.getNamespaces" in databases_js,
        "databases.js calls IrisApi.getNamespaces() for the drawer's Namespace Usage section",
    )
    # database.info only runs when "View Info" is clicked.
    check(
        "IrisApi.getDatabaseInfo" in databases_js,
        "databases.js calls IrisApi.getDatabaseInfo() for the drawer's 'View Info' action",
    )
    # database.integrity_check only runs when its button is clicked.
    check(
        "IrisApi.checkDatabaseIntegrity" in databases_js,
        "databases.js calls IrisApi.checkDatabaseIntegrity() for the drawer's "
        "'Run Integrity Check' action",
    )
    # database.create (New Database wizard) must go through the IrisApi
    # wrapper.
    check(
        "IrisApi.createDatabase" in databases_js,
        "databases.js calls IrisApi.createDatabase() for its 'New Database' wizard",
    )
    # database.mount: in the drawer, dry-run preview then confirm, via the
    # IrisApi wrapper.
    check(
        "IrisApi.mountDatabase" in databases_js,
        "databases.js calls IrisApi.mountDatabase() for the drawer's mount action",
    )
    check(
        "databases-drawer-mount" in databases_js,
        "databases.js renders into the drawer's mount elements",
    )
    # database.dismount: next to Mount, same dry-run-then-confirm flow, with
    # its own controls.
    check(
        "IrisApi.dismountDatabase" in databases_js,
        "databases.js calls IrisApi.dismountDatabase() for the drawer's dismount action",
    )
    dismount_html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    for element_id in (
        "databases-drawer-dismount-check-button",
        "databases-drawer-dismount-ack-checkbox",
        "databases-drawer-dismount-confirm-button",
        "databases-drawer-dismount-result",
    ):
        check(f'id="{element_id}"' in dismount_html, f"the {element_id!r} element exists")
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
    check('id="web-apps-description-input"' in html, "the drawer's Description input exists")
    check('id="web-apps-description-check-button"' in html, "the Description dry-run check exists")
    check('id="web-apps-description-ack-checkbox"' in html, "the Description acknowledgment checkbox exists")
    check('id="web-apps-description-confirm-button"' in html, "the Description confirm button exists")


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
    # Its mutation goes through its own api.js wrapper, never a raw fetch.
    check(
        "IrisApi.setWebAppEnabled" in web_apps_js,
        "web-apps.js's first mutation is IrisApi.setWebAppEnabled() (web_app.set_enabled)",
    )
    check(
        "IrisApi.updateWebAppDescription" in web_apps_js,
        "web-apps.js's second mutation is IrisApi.updateWebAppDescription() (web_app.update_description)",
    )
    for other_mutation in ("createNamespace", "createDatabase", "mountDatabase", "setUserEnabled", "runTaskNow", "fetch("):
        check(other_mutation not in web_apps_js, f"web-apps.js does not use {other_mutation}")
    # The backend strips the web-session ID; the frontend shouldn't look
    # for one.
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
    for mutation in ("createNamespace", "createDatabase", "mountDatabase", "setWebAppEnabled", "setUserEnabled", "fetch("):
        check(mutation not in tasks_js, f"tasks.js does not use {mutation}")
    # Its only mutation is task.run_now through the api.js wrapper.
    used = set(re.findall(r"IrisApi[.](\w+)", tasks_js))
    check(
        used == {"getTaskOverview", "getTaskManager", "getTaskDetail", "runTaskNow"},
        f"tasks.js uses exactly the three task reads plus IrisApi.runTaskNow() (found: {sorted(used)})",
    )
    # Run state comes from the backend's State (/v2/task/info), not the
    # task list's Suspended flag, which can be wrong.
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

    for element_id in (
        "security-tab-oauth",
        "security-panel-oauth",
        "security-oauth-summary-grid",
        "security-oauth-search",
        "security-oauth-server",
        "security-oauth-clients-table-body",
        "security-oauth-definitions-table-body",
        "security-oauth-configs-table-body",
        "security-oauth-resource-servers-table-body",
        "security-oauth-mappings-table-body",
    ):
        check(f'id="{element_id}"' in html, f"the {element_id!r} element exists")
    # The old OAuth2 section that showed whatever IRIS sent is gone.
    check('id="security-oauth2-server-list"' not in html, "the old pass-through OAuth2 section is removed")


def test_security_view_oauth_tab_is_get_only_and_allowlisted() -> None:
    print("Checking security.js (OAuth 2.0 tab) calls only the allowlisted OAuth endpoints...")
    security_js = (FRONTEND_DIR / "js" / "security.js").read_text(encoding="utf-8")

    used = set(re.findall(r"IrisApi[.](\w+)", security_js))
    expected = {
        "getSecurityOAuthOverview",
        "getSecurityOAuthServerClient",
        "getSecurityOAuthServerDefinition",
        "getSecurityOAuthClientConfiguration",
        "getSecurityOAuthResourceServer",
    }
    check(used == expected, f"security.js uses exactly the five read-only OAuth methods (found: {sorted(used)})")
    check("fetch(" not in security_js, "security.js makes no raw fetch() call (goes through IrisApi)")
    check(
        re.search(r'"(/api/iris/[a-z0-9\-/]*)"', security_js) is None,
        "security.js references no /api/iris/* path other than via IrisApi",
    )
    # Allowlisted data only; no secret fields are read.
    for field in (
        "ClientSecret", "ClientPassword", "InitialAccessToken", "registration_access_token", "client_secret",
        "jwks", "ServerPassword", "PrivateKeyPassword", "Authenticator", "access_token", "Password",
    ):
        check(
            re.search(rf"[.]{field}(?![A-Za-z_])|[\"']{field}[\"']", security_js) is None,
            f"security.js never reads a {field} field",
        )
    check(re.search(r"[.]innerHTML\s*=", security_js) is None, "security.js never assigns innerHTML")
    check("console." not in security_js, "security.js never logs to the console")

    api_js = (FRONTEND_DIR / "js" / "api.js").read_text(encoding="utf-8")
    for method in expected:
        match = re.search(rf"{method}: \([^)]*\) =>\s*fetchIris\(", api_js)
        check(match is not None, f"api.js's {method} is a plain GET through fetchIris()")
    for old in ("getOauth2Server", "getOauth2ClientServerDefinitions", "getOauth2ServerClients"):
        check(old not in api_js, f"api.js no longer exposes the old pass-through {old}()")


def test_security_identity_access_is_read_only_and_withholds_personal_data() -> None:
    print("Checking the Security view's Identity & Access section and security-access.js...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    for element_id in (
        "security-access-summary-grid",
        "security-privileged-table-body",
        "security-access-tabs",
        "security-users-table-body",
        "security-roles-table-body",
        "security-resources-table-body",
        "security-users-search",
        "security-roles-search",
        "security-resources-search",
        "security-roles-unlisted-hint",
        "security-drawer",
        "security-drawer-back",
    ):
        check(f'id="{element_id}"' in html, f"the {element_id!r} element exists")

    access_js = (FRONTEND_DIR / "js" / "security-access.js").read_text(encoding="utf-8")
    used = set(re.findall(r"IrisApi\.(\w+)", access_js))
    expected = {
        "getSecurityUsers", "getSecurityUserDetail", "getSecurityRoles", "getSecurityRoleDetail",
        "getSecurityRoleOwners", "getSecurityRoleAccessMap", "getSecurityResources", "getSecurityResourceDetail",
    }
    # The eight reads plus one mutation: user.set_enabled via the api.js
    # wrapper (Login Access in the user drawer).
    expected.add("setUserEnabled")
    check(
        used == expected,
        f"security-access.js uses exactly the eight Identity & Access reads plus IrisApi.setUserEnabled() "
        f"(found: {sorted(used)})",
    )
    for other_mutation in ("setWebAppEnabled", "createNamespace", "createDatabase", "mountDatabase"):
        check(other_mutation not in access_js, f"security-access.js does not use {other_mutation}")
    check("fetch(" not in access_js, "security-access.js makes no raw fetch() call (goes through IrisApi)")
    check(
        re.search(r'"(/api/iris/[a-z0-9\-/]*)"', access_js) is None,
        "security-access.js references no /api/iris/* path other than via IrisApi",
    )
    # The backend withholds personal fields; the frontend doesn't read them
    # (and IRIS sends no password/hash).
    for field in ("EmailAddress", "PhoneNumber", "PhoneProvider", "Comment", "Password", "Hash"):
        check(
            re.search(rf"\.{field}\b|[\"']{field}[\"']", access_js) is None,
            f"security-access.js never reads a {field} field",
        )
    check(re.search(r"\.innerHTML\s*=", access_js) is None, "security-access.js never assigns innerHTML")

    app_js = (FRONTEND_DIR / "js" / "app.js").read_text(encoding="utf-8")
    check(
        "loadSecurityAccess()" in app_js and "initSecurityAccessControls()" in app_js,
        "app.js loads and initializes the Identity & Access section with the Security view",
    )


def test_security_authentication_tab_is_read_only_and_withholds_smtp_username() -> None:
    print("Checking the Security view's Authentication tab and security-auth.js...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    for element_id in (
        "security-tab-authentication",
        "security-panel-authentication",
        "security-auth-summary-grid",
        "security-web-auth-methods",
        "security-web-auth-settings",
        "security-services-table-body",
        "security-services-search",
        "security-superservers-table-body",
        "security-class-access-table-body",
    ):
        check(f'id="{element_id}"' in html, f"the {element_id!r} element exists")

    auth_js = (FRONTEND_DIR / "js" / "security-auth.js").read_text(encoding="utf-8")
    used = set(re.findall(r"IrisApi[.](\w+)", auth_js))
    expected = {
        "getSecurityServices", "getSecurityServiceDetail", "getSecurityWebAuth",
        "getSecuritySuperservers", "getSecurityClassAccess",
    }
    check(used == expected, f"security-auth.js uses exactly the five read-only Authentication methods (found: {sorted(used)})")
    check("fetch(" not in auth_js, "security-auth.js makes no raw fetch() call (goes through IrisApi)")
    check(
        re.search(r'"(/api/iris/[a-z0-9\-/]*)"', auth_js) is None,
        "security-auth.js references no /api/iris/* path other than via IrisApi",
    )
    # SMTPUsername and TwoFactorFrom are withheld; the frontend only checks
    # WithheldFields for the name.
    check(
        re.search(r"[.]SMTPUsername|[.]SMTPPassword|SMTPPassword|[.]TwoFactorFrom", auth_js) is None,
        "security-auth.js never reads an SMTP username/password or two-factor sender value",
    )
    check(re.search(r"[.]innerHTML\s*=", auth_js) is None, "security-auth.js never assigns innerHTML")

    app_js = (FRONTEND_DIR / "js" / "app.js").read_text(encoding="utf-8")
    check(
        "initSecurityAuthControls()" in app_js and "refreshSecurityAuthIfLoaded()" in app_js,
        "app.js initializes the Authentication tab and refreshes it with the Security view",
    )


def test_security_wallet_tab_is_read_only_and_metadata_only() -> None:
    print("Checking the Security view's Wallet tab and security-wallet.js...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    for element_id in (
        "security-tab-wallet",
        "security-panel-wallet",
        "security-wallet-summary-grid",
        "security-wallet-none",
        "security-wallet-collections-table-body",
        "security-wallet-collections-search",
        "security-wallet-secrets-table-body",
        "security-wallet-secrets-collection",
        "security-wallet-secrets-type",
    ):
        check(f'id="{element_id}"' in html, f"the {element_id!r} element exists")

    wallet_js = (FRONTEND_DIR / "js" / "security-wallet.js").read_text(encoding="utf-8")
    used = set(re.findall(r"IrisApi[.](\w+)", wallet_js))
    expected = {"getSecurityWalletOverview", "getSecurityWalletCollectionDetail", "getSecurityWalletSecrets"}
    check(used == expected, f"security-wallet.js uses exactly the three read-only Wallet methods (found: {sorted(used)})")
    check("fetch(" not in wallet_js, "security-wallet.js makes no raw fetch() call (goes through IrisApi)")
    check(
        re.search(r'"(/api/iris/[a-z0-9\-/]*)"', wallet_js) is None,
        "security-wallet.js references no /api/iris/* path other than via IrisApi",
    )
    # Metadata only; no value fields are read.
    for field in ("Secret", "WalletSecretConfig", "Password", "PrivateKey", "Value"):
        check(
            re.search(rf"[.]{field}(?![A-Za-z])|[\"']{field}[\"']", wallet_js) is None,
            f"security-wallet.js never reads a {field} field",
        )
    check(re.search(r"[.]innerHTML\s*=", wallet_js) is None, "security-wallet.js never assigns innerHTML")
    check("console." not in wallet_js, "security-wallet.js never logs to the console")

    api_js = (FRONTEND_DIR / "js" / "api.js").read_text(encoding="utf-8")
    for method in expected:
        match = re.search(rf"{method}: \([^)]*\) =>\s*fetchIris\(", api_js)
        check(match is not None, f"api.js's {method} is a plain GET through fetchIris()")

    app_js = (FRONTEND_DIR / "js" / "app.js").read_text(encoding="utf-8")
    check(
        "initSecurityWalletControls()" in app_js and "refreshSecurityWalletIfLoaded()" in app_js,
        "app.js initializes the Wallet tab and refreshes it with the Security view",
    )


def test_security_x509_tab_is_read_only_and_metadata_only() -> None:
    print("Checking the Security view's Certificates (X.509) tab and security-x509.js...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    for element_id in (
        "security-tab-x509",
        "security-panel-x509",
        "security-x509-summary-grid",
        "security-x509-none",
        "security-x509-search",
        "security-x509-status",
        "security-x509-key",
        "security-x509-table-body",
    ):
        check(f'id="{element_id}"' in html, f"the {element_id!r} element exists")

    x509_js = (FRONTEND_DIR / "js" / "security-x509.js").read_text(encoding="utf-8")
    used = set(re.findall(r"IrisApi[.](\w+)", x509_js))
    expected = {"getSecurityX509Overview", "getSecurityX509CredentialDetail", "getSecurityX509Certificate"}
    check(used == expected, f"security-x509.js uses exactly the three read-only X.509 methods (found: {sorted(used)})")
    check("fetch(" not in x509_js, "security-x509.js makes no raw fetch() call (goes through IrisApi)")
    check(
        re.search(r'"(/api/iris/[a-z0-9\-/]*)"', x509_js) is None,
        "security-x509.js references no /api/iris/* path other than via IrisApi",
    )
    # Metadata only: just the HasPrivateKey flag, never key material.
    for field in ("PrivateKey", "PrivateKeyPassword", "PrivateKeyFile", "CertificateFile", "Password"):
        check(
            re.search(rf"[.]{field}(?![A-Za-z])|[\"']{field}[\"']", x509_js) is None,
            f"security-x509.js never reads a {field} field",
        )
    check(re.search(r"[.]innerHTML\s*=", x509_js) is None, "security-x509.js never assigns innerHTML")
    check("console." not in x509_js, "security-x509.js never logs to the console")

    api_js = (FRONTEND_DIR / "js" / "api.js").read_text(encoding="utf-8")
    for method in expected:
        match = re.search(rf"{method}: \([^)]*\) =>\s*fetchIris\(", api_js)
        check(match is not None, f"api.js's {method} is a plain GET through fetchIris()")

    app_js = (FRONTEND_DIR / "js" / "app.js").read_text(encoding="utf-8")
    check(
        "initSecurityX509Controls()" in app_js and "refreshSecurityX509IfLoaded()" in app_js,
        "app.js initializes the Certificates tab and refreshes it with the Security view",
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

    # operations.js sends everything through the IrisApi wrapper and makes
    # no authorization decisions of its own.
    check("fetch(" not in operations_js, "operations.js makes no raw fetch() call")
    referenced_paths = set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', operations_js))
    check(
        referenced_paths == set(),
        f"operations.js references no /api/iris/* path as a literal string "
        f"(found: {referenced_paths}) — every request goes through IrisApi",
    )

    # No bypass/force field, and execution is only wired to the Confirm &
    # Execute button. We look for the quoted key, not a plain substring, so
    # a comment mentioning it doesn't count.
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
    # Outside its definition, the only call should be in that click handler.
    # Comments are stripped first so mentions in prose don't count.
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

    # The assistant answers from live data, so it may call a fixed list of
    # read-only GET wrappers and nothing else. Mutations go through
    # Operations.
    allowed_reads = {
        "queryAssistant", "getInfo", "getProcesses", "getDatabases", "getDatabaseStorage",
        "getWebApps", "getTaskOverview", "getExecutionTraces", "getJournalSettings", "getMonitorDashboard",
        "getPythonDiagnostics", "searchKnowledge",
    }
    called = set(re.findall(r"IrisApi\.([A-Za-z]+)\(", ai_js))
    check(called <= allowed_reads, f"ai-assistant.js calls only read-only IrisApi methods (found: {sorted(called)})")
    mutating_methods = [
        "executeJournalPurgeArchived", "createNamespace", "createDatabase", "mountDatabase", "dismountDatabase",
        "setWebAppEnabled", "updateWebAppDescription", "setUserEnabled", "runTaskNow", "runDemoRehearsal",
    ]
    for method in mutating_methods:
        check(method not in ai_js, f"ai-assistant.js does NOT call the mutating IrisApi.{method}()")
    check(
        "isMutationRequest(" in ai_js and "answerMutation(" in ai_js,
        "ai-assistant.js answers mutation requests locally (pointing to Operations) instead of forwarding them",
    )
    check(
        "if (/purge/.test(text)) return answerMutation(text);" in ai_js,
        "ai-assistant.js never forwards a purge/journal-change message to the backend assistant",
    )

    referenced_paths = set(re.findall(r'"(/api/iris/[a-z0-9\-/]*)"', ai_js))
    check(
        referenced_paths in ({"/api/iris/assistant/query"}, set()),
        f"ai-assistant.js references only /api/iris/assistant/query as a literal path "
        f"(found: {referenced_paths or 'none, uses IrisApi.queryAssistant()'})",
    )

    # This page must never run the mutating operation or carry a
    # confirmation/bypass shortcut. We look for the actual code forms, so
    # comments mentioning them don't count.
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
    check('id="observability-trace-list"' in html, "the Trace Explorer list element exists")
    check('id="observability-detail-body"' in html, "the selected-trace details workspace exists")

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
    print("Checking investigation.js calls only its expected read-only endpoints and nothing else...")
    investigation_js = (FRONTEND_DIR / "js" / "investigation.js").read_text(encoding="utf-8")

    # getExecutionTraces reads our own trace store (not IRIS), for the
    # ±30 s related traces in the audit event detail.
    required_methods = ["IrisApi.getAuditEnabled", "IrisApi.getAuditRecords", "IrisApi.getExecutionTraces"]
    for method in required_methods:
        check(method in investigation_js, f"investigation.js calls {method}()")

    other_methods = [
        "getInfo", "getNamespaces", "getProcesses", "getDatabases", "getWebApps", "getTasks",
        "getOauth2Server", "getOauth2ClientServerDefinitions", "getOauth2ServerClients",
        "getJournalSettings", "getOperations", "queryAssistant", "executeJournalPurgeArchived",
        "getExtLangServers", "getFsAccessPurposes", "getWalletCollections",
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

    # Filtering just re-renders the list already fetched; one fetch per
    # load/Refresh (unlike investigation.js, which searches on the server).
    # Comments are stripped so a mention of "IrisApi." doesn't count.
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
    # The link is by time window because no ID ties the two together. And
    # still no mutating request anywhere.
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


def test_dashboard_is_the_landing_screen_with_activity() -> None:
    print("Checking the Dashboard surfaces recent activity (and no Quick Access section)...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    for element_id in (
        "dashboard-activity-empty",
        "dashboard-activity-table-wrapper",
        "dashboard-activity-table-body",
        "dashboard-view-observability-button",
    ):
        check(f'id="{element_id}"' in html, f"the {element_id!r} dashboard element exists")

    # The Dashboard has no Quick Access section (the sidebar covers it).
    check('id="dashboard-quicklinks"' not in html, "the Dashboard has no Quick Access section")
    check("data-quicklink=" not in html, "no dashboard quicklink buttons remain")

    dashboard_js = (FRONTEND_DIR / "js" / "dashboard.js").read_text(encoding="utf-8")
    check(
        "IrisApi.getExecutionTraces" in dashboard_js,
        "dashboard.js calls IrisApi.getExecutionTraces() for its Recent Activity section",
    )
    # Recent Operations uses the existing operations registry route.
    check(
        "IrisApi.getOperations" in dashboard_js,
        "dashboard.js calls IrisApi.getOperations() for its Recent Operations summary",
    )
    # The Tasks card uses the same backend State as the Tasks page, not the
    # list's Suspended flag (which reported false for suspended tasks).
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
    # The Dashboard stays read-only: no mutating verb, no raw fetch, and no
    # IrisApi methods beyond the five it uses plus the two Insights donuts.
    other_methods = [
        "getOauth2Server", "getOauth2ClientServerDefinitions", "getOauth2ServerClients",
        "getJournalSettings", "queryAssistant", "executeJournalPurgeArchived",
        "getExtLangServers", "getFsAccessPurposes", "getWalletCollections",
        "getAuditEnabled", "getAuditRecords",
    ]
    for method in other_methods:
        check(method not in dashboard_js, f"dashboard.js does NOT call IrisApi.{method}()")
    check("fetch(" not in dashboard_js, "dashboard.js makes no raw fetch() call (goes through IrisApi)")


def test_dashboard_live_monitoring_uses_real_read_only_sources() -> None:
    print("Checking the Dashboard's live panels read only real monitoring data and pause when hidden...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    for element_id in (
        "dashboard-live-status",
        "dashboard-live-label",
        "stat-license",
        "dashboard-monitor-warning",
        "dashboard-health-indicators",
        "dashboard-resources",
        "dashboard-storage",
        "dashboard-alert-counts",
        "dashboard-alert-list",
        "dashboard-process-state",
        "dashboard-process-namespace",
    ):
        check(f'id="{element_id}"' in html, f"the {element_id!r} dashboard element exists")

    api_js = (FRONTEND_DIR / "js" / "api.js").read_text(encoding="utf-8")
    check('"/api/iris/monitor/dashboard"' in api_js, "api.js wraps GET /api/iris/monitor/dashboard")
    check('"/api/iris/databases/storage"' in api_js, "api.js wraps GET /api/iris/databases/storage")

    dashboard_js = (FRONTEND_DIR / "js" / "dashboard.js").read_text(encoding="utf-8")
    for method in ("getMonitorDashboard", "getDatabaseStorage", "getProcesses"):
        check(f"IrisApi.{method}()" in dashboard_js, f"dashboard.js calls IrisApi.{method}()")
    check("REFRESH_INTERVAL_MS = 15000" in dashboard_js, "dashboard.js refreshes every 15 s")
    check(
        re.search(r"MAX_SAMPLES = (\d+)", dashboard_js) is not None
        and 30 <= int(re.search(r"MAX_SAMPLES = (\d+)", dashboard_js).group(1)) <= 60,
        "dashboard.js keeps 30-60 resource samples",
    )
    check(
        "visibilitychange" in dashboard_js and "document.hidden" in dashboard_js,
        "dashboard.js pauses polling while the tab is hidden and resumes when visible",
    )
    check("setInterval(" not in dashboard_js, "dashboard.js chains setTimeout so refreshes never overlap")
    check("Math.random" not in dashboard_js, "dashboard.js never generates synthetic values")
    # Status.SystemMonitor is always false on this IRIS version, so the
    # monitor state comes from the %SYS.Monitor.Control process in the
    # process list.
    check(
        "Status.SystemMonitor" not in dashboard_js.replace("Status.SystemMonitor flag", ""),
        "dashboard.js never uses IRIS's Status.SystemMonitor flag for running/stale decisions",
    )
    check(
        '"%SYS.Monitor.Control"' in dashboard_js and 'p.Nspace === "%SYS"' in dashboard_js,
        "dashboard.js detects the System Monitor from its %SYS.Monitor.Control process in %SYS",
    )
    check("Unknown (process list unavailable)" in dashboard_js, "System Monitor state is Unknown when process data fails")


def test_theme_selector_offers_three_persisted_themes() -> None:
    print("Checking the theme selector offers Midnight/Slate/Light and persists the choice...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    check('id="theme-select"' in html, "the header has a theme selector")
    for theme in ("midnight", "slate", "light"):
        check(f'value="{theme}"' in html, f"the theme selector offers {theme!r}")
    check('"icc-theme"' in html, "index.html applies the saved theme before first paint")

    css = (FRONTEND_DIR / "css" / "styles.css").read_text(encoding="utf-8")
    for theme in ("slate", "light"):
        check(f':root[data-theme="{theme}"]' in css, f"styles.css defines the {theme!r} theme tokens")

    theme_js = (FRONTEND_DIR / "js" / "theme.js").read_text(encoding="utf-8")
    check('STORAGE_KEY = "icc-theme"' in theme_js, "theme.js persists under the icc-theme key")
    check(theme_js.count("try {") >= 2, "theme.js guards every localStorage access")
    app_js = (FRONTEND_DIR / "js" / "app.js").read_text(encoding="utf-8")
    check("initThemeSelector()" in app_js, "app.js initialises the theme selector")


def test_no_mutating_http_method_anywhere_in_frontend_js() -> None:
    print("Checking no mutating HTTP method appears anywhere in frontend/js/*.js, except ten sanctioned, scoped exceptions...")
    js_dir = FRONTEND_DIR / "js"
    mutating_methods = ["PUT", "POST", "DELETE", "PATCH"]

    # The only mutating calls in the frontend are these ten POST wrappers
    # in api.js, each checked below against its own route:
    # postJournalPurgeArchived, postNamespaceCreate, postDatabaseCreate,
    # postDatabaseMount, postDatabaseDismount, postWebAppSetEnabled,
    # postWebAppUpdateDescription, postUserSetEnabled, postTaskRunNow,
    # postDemoRehearsal.
    # PUT and PATCH aren't allowed anywhere (the backend has no such routes).
    allowed_post_file = "api.js"

    for js_file in sorted(js_dir.glob("*.js")):
        content = js_file.read_text(encoding="utf-8")
        for method in mutating_methods:
            # Match the quoted verb (method: "POST"), not any word containing "post".
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

    # Each POST must go to its own existing route.
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
    check(
        '"/api/iris/security/users/set-enabled"' in api_js and "setUserEnabled:" in api_js,
        "api.js's sixth sanctioned POST (postUserSetEnabled) is scoped to "
        "/api/iris/security/users/set-enabled and exposed as IrisApi.setUserEnabled()",
    )
    check(
        '"/api/iris/tasks/run-now"' in api_js and "runTaskNow:" in api_js,
        "api.js's seventh sanctioned POST (postTaskRunNow) is scoped to "
        "/api/iris/tasks/run-now and exposed as IrisApi.runTaskNow()",
    )
    check(
        '"/api/iris/web-apps/update-description"' in api_js and "updateWebAppDescription:" in api_js,
        "api.js's eighth sanctioned POST (postWebAppUpdateDescription) is scoped to "
        "/api/iris/web-apps/update-description and exposed as IrisApi.updateWebAppDescription()",
    )
    check(
        '"/api/iris/databases/dismount"' in api_js and "dismountDatabase:" in api_js,
        "api.js's ninth sanctioned POST (postDatabaseDismount) is scoped to "
        "/api/iris/databases/dismount and exposed as IrisApi.dismountDatabase()",
    )
    check(
        '"/api/iris/demo/rehearsal"' in api_js and "runDemoRehearsal:" in api_js,
        "api.js's tenth sanctioned POST (postDemoRehearsal) is scoped to "
        "/api/iris/demo/rehearsal and exposed as IrisApi.runDemoRehearsal()",
    )

    # operations.js must use the api.js wrapper, not its own fetch() or
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

    # namespaces.js (New Namespace wizard): must use the api.js wrapper,
    # never a raw fetch() or its own authorization/confirmation logic.
    namespaces_js = (js_dir / "namespaces.js").read_text(encoding="utf-8")
    check(
        "fetch(" not in namespaces_js,
        "namespaces.js makes no raw fetch() call (goes through IrisApi)",
    )
    check(
        "IrisApi.createNamespace" in namespaces_js,
        "namespaces.js calls IrisApi.createNamespace()",
    )

    # databases.js (New Database wizard): must use the api.js wrapper,
    # never a raw fetch() or its own authorization/confirmation logic.
    databases_js = (js_dir / "databases.js").read_text(encoding="utf-8")
    check(
        "fetch(" not in databases_js,
        "databases.js makes no raw fetch() call (goes through IrisApi)",
    )
    check(
        "IrisApi.createDatabase" in databases_js,
        "databases.js calls IrisApi.createDatabase()",
    )


def test_demo_activity_is_confirmed_and_uses_only_real_traces() -> None:
    print("Checking Demo Activity: explicit confirmation, no auto-run, real traces only...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    js_dir = FRONTEND_DIR / "js"
    for element_id in (
        "dashboard-demo-activity-button",
        "demo-activity-drawer",
        "demo-activity-confirm-button",
        "demo-activity-cancel-button",
        "demo-activity-result",
        "demo-activity-steps",
    ):
        check(f'id="{element_id}"' in html, f"the {element_id!r} Demo Activity element exists")
    check(html.count("data-demo-activity-open") >= 2, "Demo Activity opens from the Dashboard and the Operations page")
    check('id="dashboard-quicklinks"' not in html, "the old Quick Access section was not reintroduced")

    demo_js = (js_dir / "demo-activity.js").read_text(encoding="utf-8")
    check("fetch(" not in demo_js, "demo-activity.js makes no raw fetch() call (goes through IrisApi)")
    code_only = re.sub(r"//.*", "", demo_js)
    code_only = re.sub(r"/\*[\s\S]*?\*/", "", code_only)
    check(
        code_only.count("IrisApi.runDemoRehearsal(") == 1
        and re.search(r"IrisApi\.runDemoRehearsal\(true[,)]", code_only) is not None,
        "demo-activity.js calls IrisApi.runDemoRehearsal(true, ...) in exactly one place (confirmed always a literal true)",
    )
    check(
        re.search(r'confirmButton\.addEventListener\("click",\s*\(\)\s*=>\s*\{\s*runConfirmed\(\);', demo_js)
        is not None
        and len(re.findall(r"(?<!function )runConfirmed\(\)", code_only)) == 1,
        "the rehearsal only runs from the Confirm & Run button's own click handler",
    )
    check(
        re.search(r'issueButton\.addEventListener\("click",\s*\(\)\s*=>\s*\{\s*runConfirmed\("issue_resolution"\);', demo_js)
        is not None
        and len(re.findall(r'runConfirmed\("issue_resolution"\)', code_only)) == 1,
        "the Issue Resolution Rehearsal only runs from its own Confirm & Run button's click handler",
    )
    for bypass_word in ("force", "bypass", "skip_confirmation", "skipConfirmation"):
        check(
            re.search(rf'["\']{bypass_word}["\']\s*:', demo_js) is None,
            f"demo-activity.js sends no {bypass_word!r} field",
        )

    for name in ("dashboard.js", "app.js", "operations.js", "observability.js"):
        content = (js_dir / name).read_text(encoding="utf-8")
        check("runDemoRehearsal" not in content, f"{name} never calls the rehearsal itself (no auto-run)")

    dashboard_js = (js_dir / "dashboard.js").read_text(encoding="utf-8")
    check("onOpenTrace(trace.trace_id)" in dashboard_js, "Recent Operations rows open their real trace")
    observability_js = (js_dir / "observability.js").read_text(encoding="utf-8")
    check("export function focusTrace" in observability_js, "observability.js exposes focusTrace() for trace links")
    app_js = (js_dir / "app.js").read_text(encoding="utf-8")
    check(
        "initDemoActivity(" in app_js and "loadExecutionTraces();" in app_js and "loadDashboard();" in app_js,
        "app.js refreshes the Dashboard and Observability from the backend after a rehearsal",
    )
    check("demo" not in (js_dir / "operations.js").read_text(encoding="utf-8").lower(),
          "Demo Activity is not part of the registry-driven operations catalog")


def test_detail_views_use_one_centered_workspace_pattern() -> None:
    print("Checking every detail panel uses the shared centered detail-workspace pattern...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    css = (FRONTEND_DIR / "css" / "styles.css").read_text(encoding="utf-8")
    js_dir = FRONTEND_DIR / "js"

    panels = re.findall(r'<aside class="(ns-drawer[^"]*)" id="([^"]+)"', html)
    check(len(panels) >= 10, f"found {len(panels)} detail panels using the shared .ns-drawer markup")
    check(
        not re.search(r'<aside class="(?![^"]*ns-drawer)[^"]*drawer', html),
        "no detail panel uses a separate, non-shared drawer implementation",
    )

    block_start = css.find("/* --- Detail workspace:")
    check(block_start != -1, "styles.css has the shared detail-workspace block")
    block = css[block_start:css.find("/* --- Responsive --- */", block_start)]
    check("transform: translate(-50%, -50%)" in block, "detail workspaces are centered on the page")
    check("calc(100vw - 48px)" in block and "calc(100vw - 24px)" in block,
          "workspace width is responsive, with safe margins on small screens")
    check("overflow-x: hidden" in block, "workspaces never scroll horizontally")

    module = (js_dir / "detail-workspace.js").read_text(encoding="utf-8")
    check("fetch(" not in module and "IrisApi" not in module, "detail-workspace.js makes no network call")
    check('"aria-modal", "true"' in module and '"role", "dialog"' in module, "panels get dialog semantics")
    check("trapTab" in module and "target.focus(" in module and "identitySelector" in module,
          "focus is kept inside and returned to the opener (or its re-rendered replacement)")
    app_js = (js_dir / "app.js").read_text(encoding="utf-8")
    check("initDetailWorkspaces();" in app_js, "app.js initialises the shared detail-workspace behaviour")

    for name in ("namespaces", "databases", "processes", "web-apps", "tasks", "security-access", "demo-activity"):
        content = (js_dir / f"{name}.js").read_text(encoding="utf-8")
        check('"Escape"' in content, f"{name}.js still closes its detail workspace on Escape")


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
        test_security_view_oauth_tab_is_get_only_and_allowlisted,
        test_security_identity_access_is_read_only_and_withholds_personal_data,
        test_security_authentication_tab_is_read_only_and_withholds_smtp_username,
        test_security_wallet_tab_is_read_only_and_metadata_only,
        test_security_x509_tab_is_read_only_and_metadata_only,
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
        test_dashboard_is_the_landing_screen_with_activity,
        test_dashboard_live_monitoring_uses_real_read_only_sources,
        test_demo_activity_is_confirmed_and_uses_only_real_traces,
        test_detail_views_use_one_centered_workspace_pattern,
        test_theme_selector_offers_three_persisted_themes,
        test_no_mutating_http_method_anywhere_in_frontend_js,
    ]
    for test in tests:
        print(f"\n{test.__name__}")
        test()
    print("\nAll frontend smoke checks passed.")


if __name__ == "__main__":
    main()
