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
  its own route, plus PUT/DELETE for /api/iris/instances/{id}; no PATCH;
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
        FRONTEND_DIR / "js" / "issue-resolver.js",
        FRONTEND_DIR / "js" / "investigation.js",
        FRONTEND_DIR / "js" / "capabilities.js",
        FRONTEND_DIR / "js" / "theme.js",
        FRONTEND_DIR / "js" / "demo-activity.js",
        FRONTEND_DIR / "js" / "detail-workspace.js",
        FRONTEND_DIR / "js" / "instances.js",
        FRONTEND_DIR / "js" / "instance-context.js",
        FRONTEND_DIR / "js" / "fleet.js",
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


def test_sidebar_navigation_order() -> None:
    print("Checking the sidebar navigation order...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    nav = re.search(r'<nav class="sidebar".*?</nav>', html, re.S)
    check(nav is not None, "the sidebar navigation exists")
    items = re.findall(r'<button class="nav-item[^"]*"[^>]*data-view="([^"]+)"[^>]*>.*?<span>([^<]+)</span>',
                       nav.group(0) if nav else "", re.S)
    expected = [
        ("fleet", "Fleet Overview"), ("dashboard", "Dashboard"), ("health-center", "Health Center"),
        ("issue-resolver", "Issue Resolver"), ("system", "System"),
        ("namespaces", "Namespaces"), ("databases", "Databases"), ("processes", "Processes"),
        ("web-apps", "Web Apps"), ("tasks", "Tasks"), ("security", "Security"), ("journal", "Journal"),
        ("operations", "Operations"), ("observability", "Observability"), ("investigation", "Investigation"),
        ("ai-assistant", "AI Assistant"), ("extensions", "Extensions"), ("capabilities", "API Explorer"),
        ("instances", "Instances"),
    ]
    check(items == expected, f"the sidebar lists its pages in the agreed order (found {[label for _, label in items]})")
    check('data-view="dashboard" aria-current="page"' in (nav.group(0) if nav else ""),
          "Dashboard is still the initially active page")


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
        r'<button class="btn btn--primary" type="button" id="databases-create-button"(?: data-primary-only)?>', html
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
    # read-only GET wrappers, plus the Copilot routes: a change is only ever
    # planned, authorized (with explicit confirmation) and executed through
    # them, and the backend re-authorizes before executing.
    allowed_reads = {
        "queryAssistant", "getInfo", "getProcesses", "getDatabases", "getDatabaseStorage",
        "getWebApps", "getTaskOverview", "getExecutionTraces", "getJournalSettings", "getMonitorDashboard",
        "getPythonDiagnostics", "searchKnowledge",
    }
    copilot_pipeline = {
        "classifyCopilotRequest", "askCopilot", "planCopilotOperation", "authorizeCopilotPlan", "executeCopilotPlan",
    }
    called = set(re.findall(r"IrisApi\.([A-Za-z]+)\(", ai_js))
    check(called <= allowed_reads | copilot_pipeline,
          f"ai-assistant.js calls only read-only IrisApi methods and the Copilot routes (found: {sorted(called)})")
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
    # A purge-archived change is a mutation request, answered locally before
    # the only call to the backend assistant (Copilot plans go through
    # authorize/execute instead).
    guard = "if (isMutationRequest(text)) return answerMutation(text);"
    check(
        "/purge ?archived|purgearchived|purge_archived/.test(text) && /\\b(set|change|update|enable|disable" in ai_js
        and guard in ai_js
        and ai_js.rindex(guard) < ai_js.index("IrisApi.queryAssistant("),
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


def test_issue_resolver_page_exists_and_is_read_only() -> None:
    print("Checking the Issue Resolver page exists and changes IRIS only through the rehearsal...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    nav_match = re.search(r'<button class="nav-item[^"]*"[^>]*data-view="issue-resolver"[^>]*>', html)
    check(nav_match is not None, 'a nav-item button with data-view="issue-resolver" exists')
    check(nav_match is not None and "disabled" not in nav_match.group(0), "the Issue Resolver nav-item is NOT disabled")
    check(
        re.search(r'<section[^>]*id="view-issue-resolver"[^>]*data-view="issue-resolver"[^>]*>', html) is not None,
        'a <section id="view-issue-resolver" data-view="issue-resolver"> exists',
    )
    check('id="issue-resolver-drawer"' in html, "the page has a detail workspace")

    js = (FRONTEND_DIR / "js" / "issue-resolver.js").read_text(encoding="utf-8")
    calls = set(re.findall(r"IrisApi\.(\w+)", js))
    check(calls == {"getIssues", "runDemoRehearsal", "getExecutionTraces", "getIssueResolutionHistory",
                    "getIssueRules", "createIssueRule", "deleteIssueRule"},
          "issue-resolver.js calls only getIssues(), the existing rehearsal, the trace list and the custom "
          f"rule routes (found {sorted(calls)})")
    check("fetch(" not in js, "issue-resolver.js makes no raw fetch() call")
    for word in ("mountDatabase", "dismountDatabase", "confirmed", "dry_run:", "dryRun"):
        check(word not in js, f"issue-resolver.js never references {word!r}")  # never builds its own request
    for key in ("resolutions", "detection_evidence", "workflow_steps", "required_privileges", "risk_level",
                "recommended_solution", "Why this solution?", "affected_namespaces", "impact_evidence"):
        check(key in js, f"issue-resolver.js renders {key!r} from the catalog")

    # Fix Preview: built in the drawer from the issue and its catalog entry,
    # for the three resolvable kinds only; no request of its own.
    preview = js.split("function fixPreview(issue, resolution) {", 1)[-1].split("\n}\n", 1)[0]
    check("IrisApi." not in preview and "fetch(" not in preview, "the Fix Preview makes no request")
    for part in ('section("Fix Preview"', '"Current → Proposed"', "resolution.operation", '"Authorization requirement"',
                 "privilegeText(resolution)", "checked by the backend when the operation runs", "resolution.confirmation_required",
                 "resolution.verification_rules", "fixBlocked(resolution)", "state detected when this page was loaded"):
        check(part in preview, f"the Fix Preview shows {part.replace('→', '->')!r}")
    check("...(res.change ? [fixPreview(issue, resolution)] : [])" in js, "the drawer adds it only where a change is described")
    check(js.count("    change: (issue) =>") == 3, "RESOURCES describes the change for the three resolvable kinds")
    check("`%Admin_${name}`" in js, "privileges are shown with their full %Admin_ names")

    app_js = (FRONTEND_DIR / "js" / "app.js").read_text(encoding="utf-8")
    check('"issue-resolver": () => loadIssueResolver()' in app_js,
          "app.js loads the Issue Resolver when its page opens")


def test_issue_resolver_presents_the_rehearsal_lifecycle() -> None:
    print("Checking the Issue Resolver shows the Issue Resolution Rehearsal as a lifecycle...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    view = re.search(r'<section[^>]*id="view-issue-resolver".*?</section>\s*\n\s*<section class="view"', html, re.S)
    check(view is not None and 'id="issue-resolver-lifecycle"' in view.group(0),
          "the rehearsal lifecycle lives on the Issue Resolver page")
    check(view is not None and 'id="issue-resolver-rehearsal-ack"' in view.group(0),
          "the rehearsal needs an explicit acknowledgement before it runs")
    check(re.search(r'data-view="[^"]*(rehearsal|demo)[^"]*"', html) is None,
          "no separate Demo/Rehearsal page or nav tab was added")

    js = (FRONTEND_DIR / "js" / "issue-resolver.js").read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", js)
    check(code.count("IrisApi.runDemoRehearsal(") == 1
          and "IrisApi.runDemoRehearsal(true, DEMO_STEPS[step].scenario)" in code,
          "the page runs only the existing IPM Issue Resolution Rehearsal steps, from one place")
    check("if (rehearsalRunning || !dom.rehearsalAck.checked || !viewedInstance().primary) return;" in code,
          "the rehearsal only runs after the acknowledgement checkbox, and only with the Primary selected")
    check(re.findall(r"\brunRehearsal\(\)", code).count("runRehearsal()") == 2,
          "runRehearsal() is defined once and called only from the Confirm & Run button")
    for label in ("Create", "Detect", "Explain", "Resolve", "Verify", "Restore", "Observe"):
        check(f'label: "{label}"' in code, f"the lifecycle has a {label!r} stage")
    for step in ("issue.dismount", "issue.detect", "issue.fix", "issue.verify", "issue.restore"):
        check(f'"{step}"' in code, f"the lifecycle is built from the rehearsal's real {step!r} step")
    check("trace_id" in code and "onOpenTrace" in code, "the lifecycle links to the real Observability traces")
    check("Math.random" not in code and "setInterval(" not in code, "no simulated progress")


def test_issue_resolver_shows_the_rehearsal_evidence_chain() -> None:
    print("Checking the rehearsal's evidence chain uses only existing workflow data...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    check('id="issue-resolver-rehearsal-evidence"' in html, "the rehearsal results have an Evidence section")
    js = (FRONTEND_DIR / "js" / "issue-resolver.js").read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", js)
    for label in ("Detection", "Impact", "Resolution", "Verification", "Observability"):
        check(f'label: "{label}"' in code, f"the evidence chain has a {label!r} stage")
    for source in ('steps.get("issue.detect")', 'steps.get("issue.fix")', 'steps.get("issue.verify")',
                   "fixTrace?.resolution?.resource", 'fixTrace.verification_result === "verified"',
                   "entry?.verification_rules", 'entry?.parameters?.find((b) => b.name === "ReadOnly")'):
        check(source in code, f"the evidence reads {source!r}")
    check(code.count("IrisApi.getExecutionTraces()") == 1 and "readFixTrace" in code,
          "the fix trace is read once from the existing trace list")
    check('"Mounted=true (operation verification: verified)"' in code and "verified ?" in code,
          "Mounted=true is only claimed when the recorded verification says verified")


def test_issue_resolver_presents_create_demo_issue() -> None:
    print("Checking the rehearsal is presented as an explicit Create Demo Issue experience...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    panel = re.search(r'<section class="info-card ir-panel ir-rehearsal[^"]*".*?</section>', html, re.S)
    check(panel is not None, "the Create Demo Issue panel exists on the Issue Resolver page")
    text = panel.group(0) if panel else ""
    check('id="issue-resolver-rehearsal-title">Demo Issue</h3>' in text, "the panel is titled Demo Issue")
    check("Create &rarr; Detect &rarr; Explain &rarr; Resolve &rarr; Verify &rarr; Restore &rarr; Observe" in text,
          "the panel states the full Create -> Observe flow")
    check("intentionally creates a real, reversible IRIS issue for demonstration" in text,
          "the panel says the issue is real, reversible and intentional")
    check("Dismounted database &mdash; IPM" in text, "the panel names the Dismounted database - IPM scenario")
    check("IPM is dismounted" in text and "left dismounted until you resolve it" in text,
          "the panel says Create dismounts IPM and leaves it dismounted until it's resolved")
    check("detects and resolves it through the normal Issue Resolver workflow" in text
          and "restores the environment" in text,
          "the panel says Resolve uses the normal workflow and restores the environment")
    check("<code>database.dismount</code>" in text and "<code>database.mount</code>" in text,
          "the panel names the existing dismount/mount operations")
    check('id="issue-resolver-rehearsal-ack"' in text and 'id="issue-resolver-rehearsal-run" disabled' in text
          and "banner--warning" in text,
          "the safety warning and acknowledgement checkbox still gate the run")
    check(re.search(r'id="issue-resolver-rehearsal-start">.*?Create Demo Issue\s*</button>', text, re.S) is not None,
          "the start button reads Create Demo Issue")

    js = (FRONTEND_DIR / "js" / "issue-resolver.js").read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", js)
    check('const DEMO_LABEL = "Intentionally created for demonstration";' in code
          and code.count("DEMO_LABEL") >= 3, "results are labelled Intentionally created for demonstration")
    check('const DEMO_SCENARIO = "Dismounted database — IPM";' in code, "results name the scenario")
    check(code.count("IrisApi.runDemoRehearsal(") == 1, "the existing rehearsal is still the only thing run")
    for word in ("demo/issue", "createDemoIssue", "localStorage", "sessionStorage"):
        check(word not in code, f"no new API or persistence ({word!r})")


def test_issue_resolver_demo_issue_has_separate_create_and_resolve_steps() -> None:
    print("Checking the demo issue runs as two explicit steps: Create, then Resolve...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    panel = re.search(r'<section class="info-card ir-panel ir-rehearsal[^"]*".*?</section>', html, re.S)
    text = panel.group(0) if panel else ""
    check(re.search(r'id="issue-resolver-demo-resolve"[^>]*disabled[^>]*>\s*Resolve Demo Issue\s*</button>', text)
          is not None, "a Resolve Demo Issue button exists, disabled until the issue is active")
    check(text.count('id="issue-resolver-rehearsal-ack"') == 1 and text.count('id="issue-resolver-rehearsal-run"') == 1,
          "both steps share the one confirmation box and checkbox")

    js = (FRONTEND_DIR / "js" / "issue-resolver.js").read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", js)
    check('scenario: "issue_create"' in code and 'scenario: "issue_resolve"' in code
          and '"issue_resolution"' not in code,
          "the page runs the issue_create and issue_resolve scenarios, not the one-click cycle")
    check('showRehearsalConfirm(true, "create")' in code and 'showRehearsalConfirm(true, "resolve")' in code,
          "each button only opens the confirmation for its own step")
    check("if (!DEMO_STEPS[step]) return;" in code, "nothing runs without a confirmed, known step")
    check("dom.demoResolve.disabled = rehearsalRunning || !issueActive || !primary;" in code
          and "dom.rehearsalStart.disabled = rehearsalRunning || issueActive || !primary;" in code,
          "Resolve is only enabled while the IPM issue is active, Create only while it isn't (both on the Primary only)")
    check('issue.kind === DISMOUNTED && String(issue.database).toUpperCase() === "IPM"' in code,
          "the active demo issue is read from the live issue list")
    check('"issue.confirm_dismounted"' in code and '"issue.fix"' in code and '"issue.verify"' in code,
          "the lifecycle uses the real Create (confirm_dismounted) and Resolve (fix, verify) steps")
    check("stays dismounted until the demo issue is resolved" in code,
          "after Create, Restore says IPM stays dismounted until it's resolved")
    for step in ("create", "resolve"):
        check(f"{step}: {{" in code.split("const SUMMARY = {", 1)[-1], f"the summary has {step!r} texts")


def test_traces_show_issue_resolution_context() -> None:
    print("Checking Observability labels traces started from an Issue Resolution workflow...")
    obs_js = (FRONTEND_DIR / "js" / "observability.js").read_text(encoding="utf-8")
    check("trace.resolution" in obs_js, "observability.js reads the trace's resolution context")
    check("Issue Resolution" in obs_js and "Issue Resolver" in obs_js,
          "observability.js shows the context in the detail and tags the trace in the list")
    db_js = (FRONTEND_DIR / "js" / "databases.js").read_text(encoding="utf-8")
    check("if (resolving) fields.resolution_issue_type = resolving.issue.kind;" in db_js,
          "databases.js sends resolution_issue_type only while resolving an issue")


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
        code_only.count("IrisApi.") == 2
        and "Promise.allSettled([IrisApi.getCapabilities(), IrisApi.getInstances()])" in code_only,
        "capabilities.js fetches its list and the instance registry once per load (filtering never re-fetches)",
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
    check("IrisApi.getTasks(" not in dashboard_js, "dashboard.js doesn't use the plain task list (there are no combined counts)")
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
        "dashboard-issues-summary",
        "dashboard-issue-list",
        "dashboard-process-state",
        "dashboard-process-namespace",
    ):
        check(f'id="{element_id}"' in html, f"the {element_id!r} dashboard element exists")

    api_js = (FRONTEND_DIR / "js" / "api.js").read_text(encoding="utf-8")
    check('"/api/iris/monitor/dashboard"' in api_js, "api.js wraps GET /api/iris/monitor/dashboard")
    check('"/api/iris/databases/storage"' in api_js, "api.js wraps GET /api/iris/databases/storage")

    dashboard_js = (FRONTEND_DIR / "js" / "dashboard.js").read_text(encoding="utf-8")
    for method in ("getMonitorDashboard", "getDatabaseStorage", "getProcesses"):
        check(f"IrisApi.{method}(id)" in dashboard_js, f"dashboard.js calls IrisApi.{method}() (for the selected instance)")
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


def test_dashboard_shows_issues_and_recommendations() -> None:
    print("Checking the Dashboard's Issues & Recommendations panel uses the live issue check...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    check("Issues &amp; Recommendations" in html, "the Dashboard has an Issues & Recommendations panel")
    check("Recent Alerts" not in html, "the old Recent Alerts panel is gone")
    dashboard_js = (FRONTEND_DIR / "js" / "dashboard.js").read_text(encoding="utf-8")
    check("IrisApi.getIssues(id)" in dashboard_js, "dashboard.js reads GET /api/iris/issues for the selected instance")
    check("resolutions" in dashboard_js, "dashboard.js explains issues with the catalog entries")
    check("No actionable issues detected." in dashboard_js, "dashboard.js has a clear no-issues state")
    check('navigateTo("issue-resolver")' in dashboard_js and "Review & Resolve" in dashboard_js,
          "Review & Resolve opens the Issue Resolver page")
    for word in ("mountDatabase", "dismountDatabase"):
        check(word not in dashboard_js, f"dashboard.js never calls {word} (nothing is run from the Dashboard)")


def test_dashboard_links_to_processes_and_issue_resolver() -> None:
    print("Checking the Dashboard links to the Processes and Issue Resolver pages...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    dashboard_js = (FRONTEND_DIR / "js" / "dashboard.js").read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", dashboard_js)

    check(re.search(r'<article class="stat-card stat-card--interactive[^"]*"[^>]*data-card="processes"', html)
          is not None and "navigateTo(card.dataset.card)" in code,
          "the Processes KPI card opens the Processes page")
    processes = re.search(r'aria-labelledby="dashboard-process-title">\s*<header class="dash-panel__head">.*?</header>',
                          html, re.S)
    check(processes is not None and 'id="dashboard-view-processes-button"' in processes.group(0),
          "the Active Processes panel header has a link button")
    check(re.search(r'viewProcessesButton\.addEventListener\("click", \(\) => \{\s*navigateTo\("processes"\);', code)
          is not None, "the Active Processes link opens the Processes page")

    issues = re.search(r'aria-labelledby="dashboard-issues-title">\s*<header class="dash-panel__head">.*?</header>',
                       html, re.S)
    check(issues is not None and 'id="dashboard-open-issue-resolver-button"' in issues.group(0),
          "the Issues & Recommendations header has an Issue Resolver link")
    check(re.search(r'openIssueResolverButton\.addEventListener\("click", \(\) => \{\s*navigateTo\("issue-resolver"\);',
                    code) is not None, "the Issues & Recommendations link opens the Issue Resolver")
    check('review.addEventListener("click", () => navigateTo("issue-resolver"));' in code,
          "each Review & Resolve action still opens the Issue Resolver")
    check('titleLink.addEventListener("click", () => navigateTo("issue-resolver"));' in code,
          "each issue title opens the Issue Resolver")


def test_dashboard_shows_recommendations_separately_from_issues() -> None:
    print("Checking the Dashboard shows recommendations, labelled apart from issues...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    panel = re.search(r'aria-labelledby="dashboard-issues-title">.*?</section>', html, re.S)
    text = panel.group(0) if panel else ""
    check('id="dashboard-recommendations"' in text and 'id="dashboard-recommendation-list"' in text,
          "the Issues & Recommendations panel has its own Recommendations list")
    check(">Recommendations</p>" in text and 'aria-label="Recommendations"' in text,
          "recommendations are labelled Recommendations, not Issues")

    js = (FRONTEND_DIR / "js" / "dashboard.js").read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", js)
    check("body?.recommendations" in code and "body?.recommendations_unavailable" in code,
          "dashboard.js reads recommendations and recommendations_unavailable from the issues response")
    check(code.count("IrisApi.getIssues(") == 1, "no extra request: recommendations come from the same GET /api/iris/issues")
    for field in ("rec.severity", "rec.title", "rec.explanation", "rec.evidence", "rec.recommended_operation",
                  "rec.parameters"):
        check(field in code, f"each recommendation shows {field!r}")
    check('review.textContent = "Review →";' in code, "each recommendation has a Review action")
    check('"journal.update_purge_archived": "operations"' in code and "navigateTo(page)" in code,
          "Review opens the existing page where the recommended operation runs")
    check('issueStatusItem("Unavailable"' in code and "unavailable.length" in code,
          "an unavailable state is shown when recommendation checks couldn't run")
    check("renderRecommendations(null)" in code, "recommendations are hidden when the issue check fails")
    check('"Review & Resolve →"' in code, "resolvable issues still show Review & Resolve")
    recs = code[code.index("function recommendationItem"):code.index("function renderRecommendations")]
    for word in ("IrisApi.", "confirmed", "fetch("):
        check(word not in recs, f"recommendations never run anything ({word!r})")


def test_web_app_issues_resolve_through_web_apps() -> None:
    print("Checking web-app issues are shown by resource and resolve on the Web Apps page...")
    no_comments = lambda text: re.sub(r"//[^\n]*", "", text)  # noqa: E731
    js_dir = FRONTEND_DIR / "js"
    resolver = no_comments((js_dir / "issue-resolver.js").read_text(encoding="utf-8"))
    web_apps = no_comments((js_dir / "web-apps.js").read_text(encoding="utf-8"))
    app_js = no_comments((js_dir / "app.js").read_text(encoding="utf-8"))
    dashboard = no_comments((js_dir / "dashboard.js").read_text(encoding="utf-8"))
    databases = no_comments((js_dir / "databases.js").read_text(encoding="utf-8"))
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    # Issue Resolver: resource-aware display and resolve action.
    for kind, page in (("database_dismounted", '"databases"'), ("web_app_namespace_missing", '"web-apps"')):
        entry = resolver.split(f"  {kind}: {{", 1)[-1].split("\n  },", 1)[0]
        check(f"page: {page}" in entry, f"{kind} issues resolve on the {page} page")
    check('"Resolve in Web Apps →"' in resolver and "issue.web_app" in resolver and "issue.namespace" in resolver,
          "web-app issues are shown by their web application and namespace")
    check("const open = resolveHandler(issue);" in resolver and "if (open) open(issue);" in resolver,
          "the drawer action opens the page for the shown issue's resource")
    check("issue_checks_unavailable" in resolver and "issue_checks_unavailable" in dashboard,
          "the Issue Resolver and Dashboard say when an issue check couldn't run")
    check('id="issue-resolver-drawer-hint"' in html, "the drawer hint names where the issue is resolved")

    # app.js hands the issue to the Web Apps page, then navigates.
    check("resolveWebAppIssue(issue);" in app_js and 'navigateTo("web-apps");' in app_js,
          "app.js opens web-app issues on the Web Apps page")

    # Web Apps: the resolution context only labels a Disable of that one app.
    check("export function resolveWebAppIssue(issue)" in web_apps, "web-apps.js accepts an Issue Resolver issue")
    check("pendingResolution.name === app.Name && target === false" in web_apps
          and "resolution_issue_type: pendingResolution.issueType" in web_apps,
          "only a Disable of the issue's app carries resolution_issue_type")
    check("...resolutionFieldsFor(app, target)" in web_apps and web_apps.count("IrisApi.setWebAppEnabled(") == 2,
          "the label goes through the existing dry run and confirm path, no new request")
    check('id="web-apps-enable-resolution"' in html, "the Enabled State section shows the resolution context")
    check("pendingResolution = null;  " in (js_dir / "web-apps.js").read_text(encoding="utf-8"),
          "closing the drawer ends the resolution context")

    # Databases: Resolve Issues only lists database issues.
    check('issue.kind === "database_dismounted"' in databases, "the Databases page only resolves database issues")
    check("issueResource(issue)" in dashboard and "issue.web_app" in dashboard,
          "the Dashboard shows each issue by its resource")


def test_journal_issue_resolves_through_operations() -> None:
    print("Checking the journal issue is shown by resource and resolves on the Operations page...")
    no_comments = lambda text: re.sub(r"//[^\n]*", "", text)  # noqa: E731
    js_dir = FRONTEND_DIR / "js"
    resolver = no_comments((js_dir / "issue-resolver.js").read_text(encoding="utf-8"))
    operations = no_comments((js_dir / "operations.js").read_text(encoding="utf-8"))
    app_js = no_comments((js_dir / "app.js").read_text(encoding="utf-8"))
    api_js = no_comments((js_dir / "api.js").read_text(encoding="utf-8"))
    dashboard = no_comments((js_dir / "dashboard.js").read_text(encoding="utf-8"))
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    entry = resolver.split("  journal_purge_archived_off: {", 1)[-1].split("\n  },", 1)[0]
    check('page: "operations"' in entry and "issue.archive_name" in entry,
          "journal issues are shown by ArchiveName and resolve on the Operations page")
    check('if (page === "operations") return onOpenOperations;' in resolver,
          "the drawer action opens the Operations page for journal issues")
    check("resolveJournalIssue(issue);" in app_js and 'navigateTo("operations");' in app_js,
          "app.js opens journal issues on the Operations page")

    check("export function resolveJournalIssue(issue)" in operations, "operations.js accepts an Issue Resolver issue")
    check("pendingResolution && target === true ? pendingResolution.issueType : null" in operations,
          "only a change to PurgeArchived=true carries resolution_issue_type")
    check(operations.count("IrisApi.executeJournalPurgeArchived(") == 2
          and "IrisApi.executeJournalPurgeArchived(target, true, issueType)" in operations,
          "the label goes through the existing confirmed execute call (plus its Check)")

    # The Check step, matching Web Apps: dry run -> preview -> checkbox -> Confirm.
    check("IrisApi.executeJournalPurgeArchived(target, true, pendingResolution.issueType, true)" in operations,
          "the Issue Resolver flow checks the change with a labelled dry run first")
    check('preview.status === "dry_run" && handlerResult && handlerResult.outcome === "success"' in operations
          and "checkedTarget = target;" in operations,
          "only a successful dry run leads to the confirm step")
    check("if (isResolutionChange(target) && !(checkedTarget === target && dom.executeAckCheckbox.checked)) return;"
          in operations, "the Issue Resolver change only executes after a successful Check and the checkbox")
    check("dom.confirmButton.disabled = !(checkedTarget === pendingTarget && dom.executeAckCheckbox.checked);"
          in operations, "Confirm stays disabled until the Check passed and the checkbox is ticked")
    check("if (isResolutionChange(target)) {" in operations and "return Boolean(pendingResolution) && target === true;"
          in operations, "the plain journal flow (no issue, or Set to No) is unchanged")
    check('id="operations-execute-ack-checkbox"' in html, "the confirm step has an acknowledgement checkbox")
    check("...(dryRun ? { dry_run: true } : {})" in api_js, "api.js only sends dry_run when asked")
    check('id="operations-execute-resolution"' in html, "the journal action shows the resolution context")
    check("...(resolutionIssueType ? { resolution_issue_type: resolutionIssueType } : {})" in api_js,
          "api.js only sends resolution_issue_type when there is one")
    check('issue.kind === "journal_purge_archived_off"' in dashboard, "the Dashboard shows the journal issue by resource")


def test_issue_resolver_catalog_entries_open_their_definition() -> None:
    print("Checking Issue Resolver catalog entries open their definition, read-only, active or not...")
    js = (FRONTEND_DIR / "js" / "issue-resolver.js").read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", js)
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    check('el("tr", "data-table__row--clickable")' in code and "row.dataset.issueType = entry.issue_type;" in code
          and "row.tabIndex = 0;" in code, "catalog rows are clickable and keyboard-focusable")
    check('dom.catalogBody.addEventListener("click"' in code and 'dom.catalogBody.addEventListener("keydown"' in code
          and code.count("openCatalogEntry(row.dataset.issueType)") == 2,
          "a click or Enter/Space on a catalog row opens its definition")

    view = code.split("function openCatalogEntry(issueType) {", 1)[-1].split("\n}\n", 1)[0]
    check("const resolution = resolutions[issueType];" in view,
          "the definition comes from the existing catalog data (resolutions)")
    for title in ("Issue type", "Detection evidence", "Explanation", "Recommended solution", "Privilege and risk",
                  "Prerequisites", "Safety restrictions", "Workflow", "Verification"):
        check(re.search(rf'section\(\s*"{title}"', view) is not None, f"the definition shows {title!r}")
    for field in ("resolution.severity", "resolution.operation", "privilegeText(resolution)",
                  "resolution.risk_level", "resolution.prerequisites", "resolution.safety_restrictions",
                  "workflowList(resolution)", "resolution.verification_rules", "evidenceTable(null, resolution)"):
        check(field in view, f"the definition reads {field!r}")
    check('"Not currently detected"' in code and "detectionBadge(detected)" in view
          and "detectedCount(issueType)" in view,
          "entries that aren't active are clearly marked Not currently detected")
    check("showDrawer();" in view and "dom.openDatabasesButton.hidden = true;" in view and "drawerIssue = null;" in view,
          "it opens the existing detail workspace, read-only, with no resolve action")
    check('class="ns-drawer ns-drawer--wide" id="issue-resolver-drawer"' in html,
          "the detail workspace is the existing shared .ns-drawer")
    check('...(issue ? ["Live value"] : [])' in code, "the catalog evidence has no live-value column")
    for word in ("IrisApi.", "fetch(", "confirmed"):
        check(word not in view, f"the catalog definition never calls anything ({word!r})")


def test_detection_only_issues_are_investigated_not_resolved() -> None:
    print("Checking detection-only issues show where to investigate and never an operation...")
    no_comments = lambda text: re.sub(r"//[^\n]*", "", text)  # noqa: E731
    js_dir = FRONTEND_DIR / "js"
    resolver = no_comments((js_dir / "issue-resolver.js").read_text(encoding="utf-8"))
    app_js = no_comments((js_dir / "app.js").read_text(encoding="utf-8"))
    dashboard = no_comments((js_dir / "dashboard.js").read_text(encoding="utf-8"))
    databases = no_comments((js_dir / "databases.js").read_text(encoding="utf-8"))

    for kind in ("system_monitor_not_running", "task_manager_not_running", "database_full"):
        check(f"  {kind}: {{" in resolver, f"the Issue Resolver shows {kind} by its resource")
        check(f'issue.kind === "{kind}"' in dashboard, f"the Dashboard shows {kind} by its resource")
    check("resolution.resolvable === false && resolution.investigation" in resolver,
          "detection-only comes from the catalog entry (resolvable false, with an investigation)")
    check("() => onInvestigate(resolution.investigation.page)" in resolver,
          "the drawer action opens the catalog's investigation page")
    check("onInvestigate: (page) => navigateTo(page)," in app_js,
          "app.js investigates by navigating to the existing page")
    check('"Investigate in ${pageLabel(resolution.investigation.page)} →"'.replace('"', "`") in resolver,
          "the action reads Investigate in <page>")
    check('section(\n    "Investigation",' in resolver and "Detection-only: the Command Center has no operation for this." in resolver,
          "detection-only drawers and definitions show an Investigation section instead of an operation")
    check("cell(typeBadge(entry))" in resolver and 'action.append(el("span", null, catalogAction(entry)), chevron);' in resolver
          and "if (isDetectionOnly(entry)) return `Investigate in ${pageLabel(entry.investigation.page)}`;" in resolver,
          "the catalog table shows Detection-only entries with where to investigate, not an operation")
    check('resolution?.resolvable === false ? "Review →" : "Review & Resolve →"' in dashboard,
          "the Dashboard offers Review (not Resolve) for detection-only issues")
    check('issue.kind === "database_dismounted"' in databases,
          "database_full is not listed in the Databases page's Resolve Issues")
    investigate = resolver.split("function investigationSection(resolution) {", 1)[-1].split("\n}\n", 1)[0]
    for word in ("IrisApi.", "fetch(", "confirmed"):
        check(word not in investigate, f"the investigation section never calls anything ({word!r})")


def test_custom_issue_rules_panel() -> None:
    print("Checking the Custom Issue Rules panel: fixed vocabulary, no code, confirmed delete...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    js = (FRONTEND_DIR / "js" / "issue-resolver.js").read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", js)
    api_js = (FRONTEND_DIR / "js" / "api.js").read_text(encoding="utf-8")
    dashboard = (FRONTEND_DIR / "js" / "dashboard.js").read_text(encoding="utf-8")

    view = re.search(r'<section[^>]*id="view-issue-resolver".*?</section>\s*\n\s*<section class="view"', html, re.S)
    text = view.group(0) if view else ""
    check('id="issue-resolver-rules-title">Custom Issue Rules</h3>' in text, "the Issue Resolver has a Custom Issue Rules panel")
    for field in ("name", "title", "severity", "signal", "operator", "value", "page", "guidance"):
        check(f'id="issue-resolver-rule-{field}"' in text, f"the rule form has a {field} field")
    for field in ("signal", "operator", "page"):
        check(re.search(rf'<select id="issue-resolver-rule-{field}"></select>', text) is not None,
              f"{field} is a select filled from the backend's fixed options")
    check('<input type="number" id="issue-resolver-rule-value"' in text, "the value is a number input")

    check("IrisApi.getIssueRules()" in code and "response.signals" in code and "response.operators" in code
          and "response.pages" in code, "the options come from GET /api/iris/issue-rules")
    check(code.count("IrisApi.createIssueRule(") == 1 and 'dom.ruleForm.addEventListener("submit", submitRule);' in code,
          "a rule is only created from the form's submit")
    check(code.count("IrisApi.deleteIssueRule(") == 1
          and 'button.dataset.action === "delete-confirm" && pendingDeleteRule === name' in code,
          "a rule is only deleted from its inline Confirm delete")
    check('postIssueRule("/api/iris/issue-rules/delete", { name, confirmed: true })' in api_js,
          "the delete request is a POST that carries confirmed=true")
    for word in ("eval(", "new Function", "innerHTML", "operation:", "fetch("):
        check(word not in code, f"the rules panel never uses {word!r}")
    check("function isCustomKind(kind)" in code and "CUSTOM_RULE_RESOURCE" in code,
          "custom-rule issues are shown by their rule, and investigated like other detection-only issues")
    check('badge("Custom rule", "status-badge--neutral")' in code, "custom entries are marked in the catalog")
    check("PERSIST_ISSUE_RULES_TO_IRIS is off" in code and "^CommandCenterIssueRule" in code,
          "the panel says whether rules are saved in IRIS or kept in memory")
    check('issue.kind.startsWith("custom:")' in dashboard, "the Dashboard shows custom-rule issues by their rule")


def test_issue_resolver_layout_separates_active_catalog_and_rules() -> None:
    print("Checking the Issue Resolver layout: tabs, three separate sections, Resolvable vs Detection-only...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    js = (FRONTEND_DIR / "js" / "issue-resolver.js").read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", js)
    css = (FRONTEND_DIR / "css" / "styles.css").read_text(encoding="utf-8")
    view = re.search(r'<section[^>]*id="view-issue-resolver".*?</section>\s*\n\s*<section class="view"', html, re.S)
    text = view.group(0) if view else ""

    # Three clearly separated sections, reachable from in-page tabs, in this order.
    sections = ["issue-resolver-active-section", "issue-resolver-catalog-section", "issue-resolver-rules-section"]
    positions = [text.find(f'id="{sid}"') for sid in sections]
    check(all(p > 0 for p in positions) and positions == sorted(positions),
          "Active Issues, Issue Catalog and Custom Issue Rules are separate sections, in that order")
    for sid, block in zip(sections, ("active", "catalog", "rules")):
        check(re.search(rf'class="info-card ir-block ir-block--{block}" id="{sid}"', text) is not None,
              f"the {block} section has its own tinted block")
        check(f'data-ir-target="{sid}"' in text, f"a tab jumps to the {block} section")
    check('.ir-tabs__tab[aria-current="true"]' in css and 'tab.setAttribute("aria-current", "true");' in code,
          "the current tab is marked with aria-current")
    check(text.find('id="issue-resolver-rehearsal-title"') > positions[-1], "the Demo Issue panel is kept, after the sections")
    check('class="info-card ir-panel ir-rehearsal ir-secondary"' in text and "Secondary &middot; Demonstration" in text,
          "the Demo Issue panel is marked as secondary content")
    counters = text.split('class="ir-counters"', 1)[-1].split("</div>\n              </div>", 1)[0]
    check(all(f"ir-counter--{kind}" in counters for kind in ("active", "resolvable", "detection"))
          and "kpi-severity" not in counters,
          "Active, Resolvable and Detection-only are the primary counters; highest severity is secondary")
    check(text.count('id="issue-resolver-drawer"') == 1, "the centered detail workspace is kept")

    # Active Issues summary counters (plus the kept highest-severity and catalog counts).
    for kpi in ("active", "resolvable", "detection", "severity", "catalog"):
        check(f'id="issue-resolver-kpi-{kpi}"' in text, f"the {kpi} count is shown")
    check("resolutions[issue.kind]?.resolvable === true" in code and "isDetectionOnly(resolutions[issue.kind])" in code,
          "Resolvable and Detection-only counts come from the catalog entries")
    check('id="issue-resolver-updated"' in text
          and "dom.updated.textContent = `${new Date().toLocaleString()} · ${viewed.name}`;" in code,
          "Active Issues shows when it was last updated, and for which instance")
    check('id="issue-resolver-refresh-button"' in text, "the refresh button is kept")

    # Resolvable vs Detection-only is obvious on cards, catalog rows and rule rows.
    check('badge("Detection-only", "ir-badge--detection")' in code and 'badge("Resolvable", "status-badge--accent")' in code,
          "Resolvable and Detection-only have distinct badges")
    check("typeBadge(resolution)" in code and "cell(typeBadge(entry))" in code,
          "cards and catalog rows show the Resolvable/Detection-only badge")
    check("card.dataset.severity = " in code and '.ir-issue[data-severity="high"]' in css,
          "issue cards carry a severity edge")
    check("if (runCardAction(event)) return;" in code
          and 'if (event.target.closest(".ir-issue__action")) return;' in code,
          "a card's action button opens its page without also opening the drawer")
    catalog = text.split('id="issue-resolver-catalog-section"', 1)[-1].split("</table>", 1)[0]
    check(re.findall(r'<th scope="col">([^<]*)</th>', catalog) == ["Issue Type", "Description", "Type", "Severity", "Action"],
          "the catalog has exactly Issue Type, Description, Type, Severity and Action columns")
    check("cell(action)," in code and code.count("row.append(") >= 1 and "cell(chevron)" not in code,
          "the catalog row has five cells, with the chevron inside the Action cell")
    check("if (detected) title.append(detectionBadge(detected));" in code,
          "only detected catalog entries are flagged in the table")
    for column in ("Name", "Title", "Signal", "Condition", "Type", "Status", "Investigate", "Actions"):
        check(f'<th scope="col">{column}</th>' in text, f"the rules table has a {column!r} column")
    check('"ir-rule-status--detected"' in code or "ir-rule-status--detected" in code,
          "custom rules show Detected / Not detected")
    for token in ("--color-error", "--color-accent", "--color-success", "--color-chart-2"):
        check(f"var({token})" in css.split("/* --- Issue Resolver layout", 1)[-1].split("/* Issue Resolver: Custom Issue Rules form", 1)[0],
              f"the section styling uses the theme token {token}")


def test_tasks_views_use_only_existing_live_task_data() -> None:
    print("Checking the Tasks views: Upcoming, Schedule and Last Runs from existing task reads only...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    js = (FRONTEND_DIR / "js" / "tasks.js").read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", js)

    for view, label in (("all", "All Tasks"), ("upcoming", "Upcoming"), ("schedule", "Schedule"), ("lastruns", "Last Runs")):
        check(f'data-view-tab="{view}"' in html and f'>{label}</button>' in html and f'id="tasks-view-{view}"' in html,
              f"the Tasks page has a {label} view")
    check('id="tasks-view-all"' in html and html.index('id="tasks-view-all"') < html.index('id="tasks-table-body"'),
          "the existing filters and table are the All Tasks view")

    # Upcoming: the overview's NextScheduled, only real dates are ordered.
    upcoming = code.split("function renderUpcoming() {", 1)[-1].split("\n}\n", 1)[0]
    check("task.NextScheduled" in upcoming and "DATETIME_PATTERN.test(next)" in upcoming,
          "Upcoming orders only NextScheduled values that are dates")
    check("Next run reported as text, not a date" in upcoming and "No next run reported" in upcoming,
          "text and empty NextScheduled values are listed as reported, not parsed")
    check("new Date(" not in upcoming and "today" not in upcoming.lower().replace('"today"', ""),
          "Upcoming groups by the IRIS date string, without timezone guessing")
    check('managerStatus !== "Running"' in upcoming, "Upcoming warns when the Task Manager isn't running")

    # Schedule: the existing detail read, no GUID resolution.
    check("IrisApi.getTaskDetail(id, selectedInstanceId())" in code and "if (scheduleDetails) {" in code,
          "Schedule reads each task's existing detail once per refresh")
    check("describeSchedule(detail)" in code, "Schedule reuses the drawer's schedule description")
    views = re.sub(r"//[^\n]*", "", js.split("// --- Views", 1)[-1].split("// --- Detail drawer", 1)[0])
    check("renderUpcoming" in views and "RunAfterGUID" not in views,
          "the views never try to resolve a Run After GUID to a task")

    # Last Runs: labelled as the most recent run only.
    check("Last Runs &mdash; most recent run of each task" in html and "This is not a run history" in html,
          "Last Runs is labelled as each task's most recent run, not a history")
    last = code.split("function renderLastRuns() {", 1)[-1].split("\n}\n", 1)[0]
    check("task.Info.LastStarted" in last and "Never run" in last and "makeResultCell(task)" in last,
          "Last Runs shows each task's last start, finish and result, and never-run tasks")
    for word in ("history", "History"):
        check(word not in last, f"Last Runs code builds no {word!r}")

    # No new requests or changes: same reads, Run Now only in the drawer.
    used = set(re.findall(r"IrisApi[.](\w+)", code))
    check(used == {"getTaskOverview", "getTaskManager", "getTaskDetail", "runTaskNow"},
          f"tasks.js still uses only the existing task reads plus Run Now (found {sorted(used)})")
    check("runTaskNow" not in views and "Run Now" not in views, "the views never offer Run Now")
    check("handleRowClick" in code and "openDrawer(Number(row.dataset.taskId))" in views,
          "rows in every view open the existing task drawer")
    check(re.search(r"task\.Suspended\b", code) is None, "the views never read the list's Suspended flag")


def test_message_log_is_read_only_with_search_levels_paging_and_detail() -> None:
    print("Checking the Message Log: read-only, search, level filter, paging, columns and detail...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    js = (FRONTEND_DIR / "js" / "message-log.js").read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", js)
    api_js = (FRONTEND_DIR / "js" / "api.js").read_text(encoding="utf-8")
    app_js = (FRONTEND_DIR / "js" / "app.js").read_text(encoding="utf-8")

    view = re.search(r'<section[^>]*id="view-investigation".*?</section>\s*\n\s*<section class="view"', html, re.S)
    text = view.group(0) if view else ""
    check('id="message-log-section"' in text and ">Message Log</h3>" in text, "the Investigation page has a Message Log section")
    for column in ("Timestamp", "PID", "Level", "Source", "Message"):
        check(f'<th scope="col">{column}</th>' in text.split('id="message-log-section"', 1)[-1],
              f"the Message Log has a {column!r} column")
    check('id="message-log-search"' in text and 'id="message-log-level"' in text, "it has a search box and a level filter")
    for level in ("Info", "Warning", "Severe", "Fatal", "Warning or higher"):
        check(f">{level}</option>" in text, f"the level filter offers {level!r}")
    check('id="message-log-page-prev"' in text and 'id="message-log-page-next"' in text, "it pages through entries")
    check('class="ns-drawer ns-drawer--wide" id="message-log-drawer"' in text, "entries open a detail workspace")

    check(set(re.findall(r"IrisApi[.](\w+)", code)) == {"getMessagesLog"}, "message-log.js only reads the message log")
    check('getMessagesLog: () => fetchIris("/api/iris/messages-log")' in api_js, "the read is a GET to /api/iris/messages-log")
    for word in ("fetch(", "innerHTML", "method:", "confirmed", "new Date(", "Date.parse"):
        check(word not in code, f"message-log.js never uses {word!r} (read-only, timestamps not parsed)")
    check("const PAGE_SIZE = 50;" in code and "filtered.slice(start, start + PAGE_SIZE)" in code,
          "search, level and paging are local over the returned entries")
    check('level === "1+" ? entry.level < 1' in code, "Warning or higher keeps levels 1-3")
    check("dom.drawerMessage.textContent = entry.message;" in code, "the detail shows the full message as text")
    check("loadMessageLog()" in app_js and "initMessageLogControls();" in app_js,
          "app.js loads the Message Log with the Investigation page")


def test_investigation_has_audit_and_message_log_tabs() -> None:
    print("Checking Investigation: two prominent tabs, each with its own content and pagination...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    inv_js = (FRONTEND_DIR / "js" / "investigation.js").read_text(encoding="utf-8")
    msg_js = (FRONTEND_DIR / "js" / "message-log.js").read_text(encoding="utf-8")
    view = re.search(r'<section[^>]*id="view-investigation".*?</section>\s*\n\s*<section class="view"', html, re.S)
    text = view.group(0) if view else ""

    check('role="tablist"' in text and 'id="investigation-tab-audit"' in text and 'id="investigation-tab-messages"' in text,
          "Investigation has Audit Investigation and Message Log tabs")
    check(">Audit Investigation</span>" in text and ">Message Log</span>" in text, "the tabs are labelled clearly")
    audit = text.split('id="investigation-panel-audit"', 1)[-1].split('id="investigation-panel-messages"', 1)[0]
    messages = text.split('id="investigation-panel-messages"', 1)[-1].split('id="message-log-drawer-backdrop"', 1)[0]
    for element in ("investigation-overview", "investigation-filter-form", "investigation-table-body", "investigation-pager",
                    "investigation-search-button", "investigation-open-observability", "investigation-kpis"):
        check(f'id="{element}"' in audit, f"the Audit tab keeps {element}")
    for element in ("message-log-section", "message-log-search", "message-log-level", "message-log-table-body",
                    "message-log-pager"):
        check(f'id="{element}"' in messages, f"the Message Log tab has {element}")
    check('id="message-log-section"' not in audit, "the Message Log is no longer at the bottom of the audit page")
    check('id="investigation-panel-messages" role="tabpanel" aria-labelledby="investigation-tab-messages" hidden' in text,
          "the Audit tab is shown first")
    check('id="message-log-drawer"' in text and 'id="investigation-drawer"' in text, "both detail drawers are kept")

    check('setInvestigationTab("audit");  // a time window is for the audit trail' in inv_js,
          "jumping to Investigation with a time window shows the Audit tab")
    check('panel.hidden = name !== tab;' in inv_js and '"ArrowLeft"' in inv_js, "tabs switch panels, with arrow keys")
    check("dom.pager.hidden = filtered.length === 0;" in msg_js, "the Message Log always shows its pagination when there are entries")
    check("dom.pager.hidden = false;" in inv_js, "the audit table keeps its own pagination")


def test_system_shows_instance_identity_and_api_findings() -> None:
    print("Checking System: instance identity from existing reads, and the API Findings documentation...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    js = (FRONTEND_DIR / "js" / "system.js").read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", js)
    view = re.search(r'<section[^>]*id="view-system".*?</section>\s*\n\s*<section class="view"', html, re.S)
    text = view.group(0) if view else ""

    # Instance & Server: only existing live reads.
    for field in ("hostname", "platform", "os", "cpus", "mgr", "uptime", "instance"):
        check(f'id="system-identity-{field}"' in text, f"the Instance & Server card shows {field}")
    check('id="system-identity-instance">Not exposed by the IRIS REST API</dd>' in text,
          "the instance name is honestly marked as not exposed, not invented")
    check(set(re.findall(r"IrisApi[.](\w+)", code)) == {"getInfo", "getPythonDiagnostics", "getMonitorDashboard"},
          "system.js uses only /info, the existing Embedded Python diagnostics and the System Dashboard")
    for field in ("diagnostics.hostname", "diagnostics.platform", "diagnostics.cpu_count", "diagnostics.manager_directory",
                  "monitor.result.Status.UpTime", "buildTargetOf(info.serverVersion)"):
        check(field in code, f"the identity card reads {field}")
    check("settled(python)" in code and "IrisApi.getPythonDiagnostics()" in code
          and "settled(IrisApi.getMonitorDashboard(selectedInstanceId()))" in code
          and 'const UNAVAILABLE = "Unavailable";' in code,
          "a failed identity read shows Unavailable without breaking the page")
    for word in ("fetch(", "innerHTML", "method:", "confirmed"):
        check(word not in code, f"system.js never uses {word!r}")

    # Layout: IRIS Information + Namespaces stacked left, Instance & Server right, even gaps.
    stack = text.split('<div class="system-stack">', 1)[-1].split("<!-- Right column", 1)[0]
    check('id="system-info-title"' in stack and 'id="system-namespaces-title"' in stack
          and 'id="system-identity-title"' not in stack,
          "IRIS Information and Namespaces share the left column; Instance & Server is on the right")
    css = (FRONTEND_DIR / "css" / "styles.css").read_text(encoding="utf-8")
    check("#view-system .system-stack {" in css and "#view-system .system-stack__fill {" in css
          and "align-items: stretch;" in css.split("#view-system .system-grid {", 1)[-1].split("}", 1)[0],
          "the two columns stretch to equal height with one gap in the left stack")

    # API Integration Notes: secondary, collapsible, at the bottom, static documentation.
    findings = text.split('id="system-api-findings"', 1)[-1]
    check('<details class="info-card info-card--wide system-notes" id="system-api-findings">' in text
          and "<details" in text and " open" not in text.split('id="system-api-findings"', 1)[0][-80:],
          "the notes are a collapsed <details> section")
    check('id="system-api-findings-title">API Integration Notes</span>' in findings and "API Findings" not in text,
          "the section is called API Integration Notes")
    check(text.index('id="system-api-findings"') > text.index('id="system-privileges-title"'),
          "the notes sit at the bottom, after Session Privileges")
    check(findings.count("<tr>") == 9, "the notes keep exactly the 8 findings (plus the header row)")
    for column in ("Area", "IRIS API behavior", "Command Center (read-only)"):
        check(f'<th scope="col">{column}</th>' in findings, f"the findings table has a {column!r} column")
    for area in ("Message log", "Instance identity", "Task state", "Task timing", "Database info", "API Management",
                 "Web application updates", "Alerts"):
        check(f'<td class="data-table__cell">{area}</td>' in findings, f"the findings document {area!r}")
    check("system-api-findings" not in code, "the findings are static documentation (nothing is fetched for them)")


def test_theme_selector_offers_four_persisted_themes() -> None:
    print("Checking the theme selector offers Midnight/Slate/Professional/Light and persists the choice...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    check('id="theme-select"' in html, "the header has a theme selector")
    for theme in ("midnight", "slate", "professional", "light"):
        check(f'value="{theme}"' in html, f"the theme selector offers {theme!r}")
    check('"icc-theme"' in html, "index.html applies the saved theme before first paint")

    css = (FRONTEND_DIR / "css" / "styles.css").read_text(encoding="utf-8")
    for theme in ("slate", "professional", "light"):
        check(f':root[data-theme="{theme}"]' in css, f"styles.css defines the {theme!r} theme tokens")

    theme_js = (FRONTEND_DIR / "js" / "theme.js").read_text(encoding="utf-8")
    check('STORAGE_KEY = "icc-theme"' in theme_js, "theme.js persists under the icc-theme key")
    check('"professional"' in theme_js, "theme.js accepts the professional theme")
    check('savedTheme === "professional"' in html, "index.html applies a saved professional theme before first paint")
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
    # postDemoRehearsal, and postIssueRule (Custom Issue Rules create/delete).
    # PATCH isn't allowed anywhere. PUT and DELETE appear only in api.js, for
    # the instance routes (sendInstanceRequest, checked below).
    allowed_post_file = "api.js"

    # health-center.js lists the IRIS endpoints its report is built from, as
    # text; one of them is the backend's own POST /v2/database-dir/info read.
    # That label (and only it) is not a request.
    display_only = {"health-center.js": 'method: "POST",\n    path: "/v2/database-dir/info",'}

    for js_file in sorted(js_dir.glob("*.js")):
        content = js_file.read_text(encoding="utf-8")
        if js_file.name in display_only:
            label = display_only[js_file.name]
            check(label in content and "fetch(" not in content,
                  f"{js_file.relative_to(REPO_ROOT)} only lists that IRIS endpoint and makes no request itself")
            content = content.replace(label, "")
        for method in mutating_methods:
            # Match the quoted verb (method: "POST"), not any word containing "post".
            pattern = rf'["\']{method}["\']'
            found = re.search(pattern, content) is not None
            if method in ("PUT", "DELETE") and js_file.name == allowed_post_file:
                calls = re.findall(rf'sendInstanceRequest\("{method}", instancePath\(id\)', content)
                check(
                    found and len(re.findall(pattern, content)) == len(calls) == 1,
                    f"{js_file.relative_to(REPO_ROOT)} uses {method} only for /api/iris/instances/{{id}}",
                )
                continue
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
        'postIssueRule("/api/iris/issue-rules", rule)' in api_js
        and 'postIssueRule("/api/iris/issue-rules/delete", { name, confirmed: true })' in api_js,
        "api.js's Custom Issue Rules POSTs are scoped to /api/iris/issue-rules and /api/iris/issue-rules/delete",
    )
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
    drawer = re.search(r'id="demo-activity-intro".*?id="demo-activity-issue-button"[^<]*</button>', html, re.S)
    drawer_text = drawer.group(0) if drawer else ""
    check("Create Demo Issue (separate, manual)</h4>" in drawer_text
          and ">Confirm &amp; Create Demo Issue</button>" in drawer_text
          and "Issue Resolution Rehearsal" not in drawer_text,
          "the drawer uses the Issue Resolver's Create Demo Issue terminology")
    check("Intentionally creates a real, reversible IRIS issue for demonstration purposes" in drawer_text
          and "Dismounted database &mdash; IPM" in drawer_text,
          "the drawer says the demo issue is intentional, real and reversible")

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


def test_instances_page_uses_instance_routes_and_confirmed_operations() -> None:
    print("Checking the Instances page: nav, view, routes, Primary protection and confirmation...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    js = (FRONTEND_DIR / "js" / "instances.js").read_text(encoding="utf-8")
    api_js = (FRONTEND_DIR / "js" / "api.js").read_text(encoding="utf-8")
    app_js = (FRONTEND_DIR / "js" / "app.js").read_text(encoding="utf-8")

    nav = re.search(r'<button class="nav-item"[^>]*data-view="instances"[^>]*>', html)
    check(nav is not None and "disabled" not in nav.group(0), "the Instances nav item exists and is enabled")
    check('<section class="view" id="view-instances" data-view="instances"' in html, "the Instances view exists")
    check("initInstancesControls();" in app_js and "instances: () => loadInstances({ checkSystem: true })," in app_js,
          "app.js wires the page and reloads it (checking the Primary and Docker-managed instance) each time it is opened")

    used = sorted(set(re.findall(r"IrisApi\.(\w+)", js)))
    check(used == ["checkInstance", "createInstance", "deleteInstance", "getInstances", "setInstanceActive",
                   "testInstanceConnection", "updateInstance"], f"instances.js calls only the instance API ({used})")
    check("fetch(" not in js, "instances.js makes no raw fetch() call (goes through IrisApi)")
    for route in ('"/api/iris/instances"', '"/api/iris/instances/test"'):
        check(route in api_js, f"api.js targets the {route} route")

    # Real changes (confirmed=true, dry_run=false) only from the confirm buttons.
    real_calls = re.findall(r"IrisApi\.(?:createInstance|updateInstance)\([^;\n]*true, false\)|runConfirmAction\(confirmState, false\)", js)
    check(len(real_calls) == 3, "create/update/activate/deactivate/delete run for real only from the submit/confirm handlers")
    check(js.count("runConfirmAction(confirmState, true)") == 1 and "updateInstance(formState.instance.id, changes, true, true)" in js,
          "edit and activate/deactivate/delete are previewed with a dry run first")
    check("formState.tested = check.status === \"compatible\"" in js and "!formState.tested" in js,
          "Add Instance is enabled only after a compatible connection test")
    check('id="instance-form-submit-button" disabled' in html and 'id="instance-confirm-button" disabled' in html,
          "the add/update and confirm buttons start disabled")
    check("ackCheckbox.checked" in js and 'id="instance-confirm-ack-checkbox"' in html and 'id="instance-form-ack-checkbox"' in html,
          "every change needs the explicit confirmation checkbox")

    # The Primary is protected in the UI (the backend also refuses).
    check("if (instance.primary) {" in js and "disabled: true, title: reason" in js,
          "the Primary's Edit and Delete are disabled and it has no Deactivate")
    check('!instance.primary && !instance.docker_managed) openForm("edit"' in js
          and '!instance.primary && !(action === "delete" && instance.docker_managed)) {' in js,
          "row actions never open a change dialog for the Primary, nor Edit/Delete for the Docker-managed instance")

    # Passwords: only read from the field to send, never displayed, stored or logged.
    check("console." not in js, "instances.js doesn't log")
    check(re.findall(r"password\.value(?! = \"\")", js) and all(
        "textContent" not in line and "innerHTML" not in line for line in js.splitlines() if "password.value" in line),
        "the password field value is never written into the page")
    check("localStorage" not in js and "sessionStorage" not in js, "nothing is kept in browser storage")
    check('formDom.password.value = "";' in js and 'autocomplete="new-password"' in html,
          "the password field is cleared when the dialog closes or after a successful save")
    check("placeholder = isEdit ? \"Enter new password to change (leave blank to keep current)\"" in js
          and "if (formDom.password.value) changes.password" in js,
          "a blank password on Edit keeps the stored one (it isn't sent)")
    check("innerHTML" not in js, "instances.js renders with textContent only")


def test_instance_selector_is_in_page_headers_and_context_only() -> None:
    print("Checking the instance selector: page-header placement, selectable instances only, context-only, no credentials...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    js = (FRONTEND_DIR / "js" / "instance-context.js").read_text(encoding="utf-8")
    app_js = (FRONTEND_DIR / "js" / "app.js").read_text(encoding="utf-8")
    instances_js = (FRONTEND_DIR / "js" / "instances.js").read_text(encoding="utf-8")

    header = re.search(r'<header class="app-header">.*?</header>', html, re.S)
    header_html = header.group(0) if header else ""
    check("instance-selector" not in header_html, "the application header has no instance selector")
    check(html.count('id="instance-selector"') == 1, "there is exactly one selector")
    dashboard_header = re.search(r'<section class="view" id="view-dashboard".*?<div class="view__header">(.*?)\n          </div>\n', html, re.S)
    selector_html = dashboard_header.group(1) if dashboard_header else ""
    check('id="instance-selector"' in selector_html and 'role="listbox"' in selector_html
          and 'aria-haspopup="listbox"' in selector_html, "it starts in the Dashboard's page header (button + listbox)")
    check("initInstanceSelector();" in app_js, "app.js initialises the selector")
    selector_views = re.search(r"const SELECTOR_VIEWS = new Set\(\[\.\.\.INSTANCE_VIEWS, ([^\]]*)\]\);", app_js)
    check(selector_views is not None and selector_views.group(1) == '"dashboard", "health-center"',
          "the selector is placed on the instance pages plus the Dashboard and Health Center")
    instance_views = re.search(r"const INSTANCE_VIEWS = new Set\(\[(.*?)\]\);", app_js, re.S)
    check(instance_views is not None and '"fleet"' not in instance_views.group(1), "fleet gets no instance selector")
    for name in ("issue-resolver", "operations", "observability", "capabilities"):
        check(instance_views is not None and f'"{name}"' in instance_views.group(1), f"{name} gets the instance selector")
    check("const shown = SELECTOR_VIEWS.has(view);" in app_js and "placeInstanceSelector(shown ?" in app_js,
          "app.js moves it into the open page's header")
    check("if (shown) refreshInstanceContext();" in app_js, "opening an instance page checks the instances again")
    check('const VIEWS_WITH_PRIMARY_ONLY_ACTIONS = new Set(["issue-resolver", "operations"]);' in app_js
          and "context-notice-primary" not in html and "PRIMARY_ONLY_VIEWS" not in app_js,
          "Issue Resolver and Operations read the selected instance; their changes are marked Primary only (no page is blocked)")
    check("updateInstanceContextList(instances);" in instances_js, "the Instances screen refreshes the selector after it reloads")

    used = sorted(set(re.findall(r"IrisApi\.(\w+)", js)))
    check(used == ["getInfo", "getInstances"],
          f"instance-context.js only reads GET /api/iris/instances and, to check reachability, GET /api/iris/info ({used})")
    check("fetch(" not in js, "instance-context.js makes no raw fetch() call")
    check("All Active Instances" not in js and "ALL_ACTIVE" not in js, "there is no All Active Instances option")
    check("selectable: active && (primary || reachable.has(String(instance.id)))" in js
          and "checkInstance: (id) => IrisApi.getInfo(id).then(() => true, () => false)" in js
          and "filter((entry) => entry.selectable)" in js,
          "only active instances that answer now (or the Primary) are offered")
    check('STORAGE_KEY = "icc-instance-context"' in js and "localStorage" in js, "the choice is persisted in localStorage")
    check("CONTEXT_EVENT" in js and "export function getInstanceContext" in js and "export function onInstanceContextChange" in js,
          "the context is exposed as getInstanceContext()/onInstanceContextChange() and a document event")
    check("credential_ref" not in js and ".password" not in js and ".username" not in js and "innerHTML" not in js,
          "the context keeps no credential fields and renders with textContent only")

    # Pages that read IRIS data follow the selector; Primary-only pages and
    # Command Center's own data don't.
    for name in ("dashboard", "health-center", "system", "namespaces", "processes", "databases", "web-apps", "tasks",
                 "security", "security-access", "security-auth", "security-wallet", "security-x509", "journal",
                 "investigation", "extensions", "ai-assistant", "issue-resolver", "operations", "observability",
                 "capabilities"):
        check("instance-context" in (FRONTEND_DIR / "js" / f"{name}.js").read_text(encoding="utf-8"),
              f"{name}.js reads the selected instance")
    issue_js = (FRONTEND_DIR / "js" / "issue-resolver.js").read_text(encoding="utf-8")
    operations_js = (FRONTEND_DIR / "js" / "operations.js").read_text(encoding="utf-8")
    check("IrisApi.getIssues(selectedInstanceId())" in issue_js, "Issue Resolver checks the selected instance for issues")
    check("IrisApi.getJournalSettings(selectedInstanceId())" in operations_js
          and "IrisApi.executeJournalPurgeArchived(target, true, issueType)" in operations_js
          and '["Runs on", "Primary instance only"]' in operations_js,
          "Operations reads the selected instance and runs its change on the Primary only, which every card says")
    for name in ("message-log", "demo-activity"):
        check("instance-context" not in (FRONTEND_DIR / "js" / f"{name}.js").read_text(encoding="utf-8"),
              f"{name}.js stays on the Primary / Command Center data")


def test_fleet_overview_is_read_only_and_reads_each_instance() -> None:
    print("Checking the Fleet Overview: nav, view, read-only per-instance reads...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    js = (FRONTEND_DIR / "js" / "fleet.js").read_text(encoding="utf-8")
    app_js = (FRONTEND_DIR / "js" / "app.js").read_text(encoding="utf-8")

    check('data-view="fleet"' in html and '<section class="view" id="view-fleet" data-view="fleet"' in html,
          "the Fleet Overview nav item and view exist")
    check("fleet: () => loadFleet()," in app_js and "initFleetControls();" in app_js, "app.js wires the Fleet Overview")
    used = sorted(set(re.findall(r"IrisApi\.(\w+)", js)))
    check(used == ["getDatabases", "getHealthReport", "getInfo", "getInstances", "getMonitorDashboard", "getNamespaces",
                   "getProcesses", "getTasks", "getWebApps"],
          f"fleet.js only reads ({used})")
    check("fetch(" not in js and "innerHTML" not in js, "fleet.js goes through IrisApi and renders with textContent")
    check("const id = instance.primary ? undefined : instance.id;" in js and '"all"' not in js.split("readInstance")[1][:500],
          "each instance is read with its own id (the Primary without ?instance=), never ?instance=all")
    check("activeInstances().map((instance) => readInstance(instance, full, token))" in js,
          "only active instances are read, each on its own")


def test_explain_this_screen_is_read_only_and_covers_nine_pages() -> None:
    print("Checking Screen Insights: shared button and side panel, nine pages, no requests...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    js = (FRONTEND_DIR / "js" / "explain-screen.js").read_text(encoding="utf-8")
    app_js = (FRONTEND_DIR / "js" / "app.js").read_text(encoding="utf-8")

    check(re.search(r'id="explain-screen-button" hidden>\s*<span[^>]*>&#9432;</span>\s*Screen Insights\s*</button>', html)
          is not None, "the header button reads Screen Insights")
    for marker in ('id="explain-screen-button"',
                   'class="ns-drawer ns-drawer--side explain-screen" id="explain-screen-drawer" hidden',
                   'id="explain-screen-backdrop"', 'id="explain-screen-close"', 'id="explain-screen-body"',
                   "This explanation is built from the current Command Center view."):
        check(marker in html, f"index.html has {marker!r}")
    check("IrisApi" not in js and "fetch(" not in js and "innerHTML" not in js,
          "explain-screen.js makes no request and renders with textContent")
    views = ["dashboard", "health-center", "fleet", "issue-resolver", "operations", "observability", "security",
             "capabilities", "investigation"]
    table = js.split("export const EXPLANATIONS = {", 1)[1].split("\n};", 1)[0]
    explained = re.findall(r'^  "?([a-z-]+)"?: \{$', table, re.M)
    check(sorted(explained) == sorted(views), f"exactly the nine pages are explained (found {explained})")
    for view in views:
        check(f'data-view="{view}"' in html, f"{view} is a real page")
    fact_ids = re.findall(r'^ +\["[A-Z][^"]*", "([a-z0-9-]+)"\]', table, re.M)
    fact_ids += re.findall(r'^ +(?:note|updated): "([a-z0-9-]+)"', table, re.M)
    check(len(fact_ids) >= 30, f"the snapshots read the pages' own elements (found {len(fact_ids)})")
    for fact_id in fact_ids:
        check(f'id="{fact_id}"' in html, f"live fact {fact_id!r} is an element the page already renders")
    for related in re.findall(r'^ +related: \[([^\]]*)\]', table, re.M):
        for view in re.findall(r'"([a-z-]+)"', related):
            check(re.search(rf'class="nav-item[^"]*" type="button" data-view="{view}"', html) is not None,
                  f"related area {view!r} is a nav page")
    for title in ("Overview", "Current snapshot", "All active instances", "What matters here", "Key terms",
                  "Related areas"):
        check(f'"{title}"' in js, f"the briefing has a {title!r} section")
    check("navigateTo(view);" in js and "closeExplanation();" in js, "a related area closes the panel, then navigates")
    check("dom.drawer.scrollTop = 0;" in js, "the panel always opens at the top")
    check(".ns-drawer.ns-drawer--side {" in (FRONTEND_DIR / "css" / "styles.css").read_text(encoding="utf-8"),
          "styles.css makes it a side panel")
    check('"Not loaded yet. Use Refresh."' in js, "a value that hasn't loaded says so")
    check("allInstances: true" in js and "Covers every active instance" in js,
          "Fleet Overview uses its own all-instances context")
    check('import { initExplainScreen, placeExplainButton } from "./explain-screen.js";' in app_js
          and "initExplainScreen(() => currentView);" in app_js
          and app_js.count("placeExplainButton(") == 2,
          "app.js wires the button and places it in the open page's header")


def test_dashboard_needs_attention_reuses_loaded_data_and_only_links() -> None:
    print("Checking the Dashboard's Needs Attention: existing data, links only, no new requests...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    js = (FRONTEND_DIR / "js" / "dashboard.js").read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", js)
    check('id="dashboard-attention-panel"' in html and "Needs Attention" in html and 'id="dashboard-attention-list"' in html,
          "the Dashboard has a Needs Attention panel")
    check(html.index('id="dashboard-attention-panel"') < html.index('id="dashboard-main-grid"'),
          "it sits under the KPI cards, above the panels")
    calls = sorted(set(re.findall(r"IrisApi\.(\w+)\(", code)))
    check(calls == ["getDatabaseStorage", "getDatabases", "getExecutionTraces", "getInfo", "getIssues", "getMonitorDashboard",
                    "getNamespaces", "getOperations", "getProcesses", "getTaskOverview", "getWebApps"],
          f"dashboard.js reads only its existing routes (found {calls})")
    check(code.count("IrisApi.getIssues(") == 1 and code.count("IrisApi.getTaskOverview(") == 1,
          "Needs Attention reuses the issues and task overview the page already reads")
    attention = code.split("export function attentionItems(", 1)[1].split("\nfunction renderAttention(", 1)[0]
    check("IrisApi" not in attention and "fetch(" not in attention, "the detection itself makes no request")
    for fact in ('task.State === "Suspended"', "TASK_ERROR_STATUS_CODES.has(String(task.Info?.Status))",
                 "issue_checks_unavailable", "resolutions[issue.kind]"):
        check(fact in attention, f"it uses {fact!r} as IRIS or the issue check reports it")
    check('["View Issues →", "issue-resolver"]' in attention and '["View Tasks →", "tasks"]' in attention
          and "navigateTo(view)" in code, "each item links to its existing page")
    check("renderAttention(r.issues, r.tasks);" in code, "it renders from the same refresh results")


def test_security_overview_is_read_only_inventory_and_findings() -> None:
    print("Checking the Security Overview: existing read routes, IRIS-reported findings, links only...")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    js = (FRONTEND_DIR / "js" / "security-overview.js").read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", js)
    security_js = (FRONTEND_DIR / "js" / "security.js").read_text(encoding="utf-8")
    app_js = (FRONTEND_DIR / "js" / "app.js").read_text(encoding="utf-8")

    check('id="security-overview-section"' in html and 'id="security-overview-cards"' in html
          and 'id="security-overview-findings"' in html, "the Security page has a Security Overview")
    check(html.index('id="security-overview-section"') < html.index('id="security-access-section"'),
          "it sits above Identity & Access")
    calls = sorted(set(re.findall(r"IrisApi\.(\w+)\(", code)))
    check(calls == ["getAuditEnabled", "getSecurityServices", "getSecurityWalletOverview", "getSecurityX509Overview"],
          f"security-overview.js reads only existing GET routes (found {calls})")
    check("fetch(" not in code and "innerHTML" not in code and "setUserEnabled" not in code,
          "it makes no other request, changes nothing and renders with textContent")
    check('import { validityOf } from "./security-x509.js";' in js
          and "export function validityOf(" in (FRONTEND_DIR / "js" / "security-x509.js").read_text(encoding="utf-8"),
          "certificate validity uses the Certificates tab's own rule")
    check('AuthenticationMethods.includes("Unauthenticated")' in code and "auditEnabled === false" in code,
          "service and audit findings come from what IRIS reports")
    check("Secrets.length" in code and "secret.Name" not in code and "SecretValue" not in code,
          "Wallet secrets are only counted")
    check(security_js.count("setOAuthOverview(") == 3, "security.js shares its OAuth 2.0 overview (no second request)")
    check("loadSecurityOverview()," in app_js, "app.js loads it with the Security page")


def main() -> None:
    tests = [
        test_expected_files_exist_and_are_non_empty,
        test_frontend_can_be_served,
        test_api_paths_match_real_backend_routes,
        test_sidebar_navigation_order,
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
        test_issue_resolver_page_exists_and_is_read_only,
        test_issue_resolver_presents_the_rehearsal_lifecycle,
        test_issue_resolver_shows_the_rehearsal_evidence_chain,
        test_issue_resolver_presents_create_demo_issue,
        test_issue_resolver_demo_issue_has_separate_create_and_resolve_steps,
        test_traces_show_issue_resolution_context,
        test_investigation_nav_and_view_exist_and_are_enabled,
        test_investigation_view_uses_only_expected_endpoints,
        test_capabilities_nav_and_view_exist_and_are_enabled,
        test_capabilities_view_uses_only_expected_endpoint,
        test_observability_investigation_cross_link_exists,
        test_dashboard_is_the_landing_screen_with_activity,
        test_dashboard_live_monitoring_uses_real_read_only_sources,
        test_demo_activity_is_confirmed_and_uses_only_real_traces,
        test_detail_views_use_one_centered_workspace_pattern,
        test_dashboard_shows_issues_and_recommendations,
        test_dashboard_links_to_processes_and_issue_resolver,
        test_dashboard_shows_recommendations_separately_from_issues,
        test_web_app_issues_resolve_through_web_apps,
        test_journal_issue_resolves_through_operations,
        test_issue_resolver_catalog_entries_open_their_definition,
        test_detection_only_issues_are_investigated_not_resolved,
        test_custom_issue_rules_panel,
        test_issue_resolver_layout_separates_active_catalog_and_rules,
        test_tasks_views_use_only_existing_live_task_data,
        test_message_log_is_read_only_with_search_levels_paging_and_detail,
        test_investigation_has_audit_and_message_log_tabs,
        test_system_shows_instance_identity_and_api_findings,
        test_theme_selector_offers_four_persisted_themes,
        test_no_mutating_http_method_anywhere_in_frontend_js,
        test_instances_page_uses_instance_routes_and_confirmed_operations,
        test_instance_selector_is_in_page_headers_and_context_only,
        test_fleet_overview_is_read_only_and_reads_each_instance,
        test_explain_this_screen_is_read_only_and_covers_nine_pages,
        test_dashboard_needs_attention_reuses_loaded_data_and_only_links,
        test_security_overview_is_read_only_inventory_and_findings,
    ]
    for test in tests:
        print(f"\n{test.__name__}")
        test()
    print("\nAll frontend smoke checks passed.")


if __name__ == "__main__":
    main()
