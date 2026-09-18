"""Minimal frontend smoke test — no test framework introduced for this.

Run directly:  python tests/test_frontend_smoke.py
(uses the backend's existing venv, since it needs to import the real
FastAPI app to compare routes — see backend/.venv)

Checks, per Phase 3 Step 1's minimum bar ("verify the frontend can be
served and that its API paths match the existing backend routes"),
extended in Phase 3 Step 2 for the System view and Phase 3 Step 3 for the
Processes view:

1. The expected frontend files exist and are non-empty.
2. A plain static file server can actually serve frontend/index.html.
3. Every /api/iris/* path referenced in frontend/js/api.js is a REAL,
   currently-registered route on the backend FastAPI app (compared via the
   app's own OpenAPI schema, not by guessing/duplicating the route list).
4. (Step 2) The System nav item and view exist in the markup and the nav
   item is enabled (not `disabled`).
5. (Step 2) system.js calls GET /api/iris/info and no other endpoint.
6. (Step 3) The Processes nav item and view exist in the markup and the
   nav item is enabled (not `disabled`).
7. (Step 3) processes.js calls GET /api/iris/processes and no other
   endpoint, and renders into the processes table body.
8. (general regression guard) No mutating HTTP method string
   ("PUT"/"POST"/"DELETE"/"PATCH") appears anywhere in frontend/js/*.js —
   this is intentionally broad so it keeps guarding every future view,
   not just System/Processes.

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
        FRONTEND_DIR / "js" / "nav.js",
        FRONTEND_DIR / "js" / "processes.js",
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


def test_no_mutating_http_method_anywhere_in_frontend_js() -> None:
    print("Checking no mutating HTTP method appears anywhere in frontend/js/*.js...")
    js_dir = FRONTEND_DIR / "js"
    mutating_methods = ["PUT", "POST", "DELETE", "PATCH"]
    for js_file in sorted(js_dir.glob("*.js")):
        content = js_file.read_text(encoding="utf-8")
        for method in mutating_methods:
            # Looks for the method as a quoted HTTP verb (e.g. method: "POST"),
            # not as an incidental substring (e.g. a word containing "post").
            pattern = rf'["\']{method}["\']'
            check(
                re.search(pattern, content) is None,
                f"{js_file.relative_to(REPO_ROOT)} does not reference HTTP method {method!r}",
            )


def main() -> None:
    tests = [
        test_expected_files_exist_and_are_non_empty,
        test_frontend_can_be_served,
        test_api_paths_match_real_backend_routes,
        test_system_nav_and_view_exist_and_are_enabled,
        test_system_view_uses_only_get_info,
        test_processes_nav_and_view_exist_and_are_enabled,
        test_processes_view_uses_only_get_processes,
        test_no_mutating_http_method_anywhere_in_frontend_js,
    ]
    for test in tests:
        print(f"\n{test.__name__}")
        test()
    print("\nAll frontend smoke checks passed.")


if __name__ == "__main__":
    main()
