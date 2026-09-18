"""Minimal frontend smoke test — no test framework introduced for this.

Run directly:  python tests/test_frontend_smoke.py
(uses the backend's existing venv, since it needs to import the real
FastAPI app to compare routes — see backend/.venv)

Checks, per Phase 3 Step 1's minimum bar ("verify the frontend can be
served and that its API paths match the existing backend routes"):

1. The expected frontend files exist and are non-empty.
2. A plain static file server can actually serve frontend/index.html.
3. Every /api/iris/* path referenced in frontend/js/api.js is a REAL,
   currently-registered route on the backend FastAPI app (compared via the
   app's own OpenAPI schema, not by guessing/duplicating the route list).

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


def main() -> None:
    tests = [
        test_expected_files_exist_and_are_non_empty,
        test_frontend_can_be_served,
        test_api_paths_match_real_backend_routes,
    ]
    for test in tests:
        print(f"\n{test.__name__}")
        test()
    print("\nAll frontend smoke checks passed.")


if __name__ == "__main__":
    main()
