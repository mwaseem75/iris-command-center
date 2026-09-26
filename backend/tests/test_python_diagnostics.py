"""Tests for the Embedded Python diagnostics and GET /api/iris/python/diagnostics.
The Native API handle is a fake that records every call.
"""

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.dependencies import get_python_diagnostics
from app.embedded_python.diagnostics import (
    EmbeddedPythonDiagnostics,
    EmbeddedPythonUnavailableError,
    PythonDiagnostics,
    parse_meminfo,
)
from app.main import app

MEMINFO = "MemTotal:        8017536 kB\nMemFree:         6165072 kB\nMemAvailable:    6511168 kB\n"


class _FakePyObject:
    """Fake IRISObject wrapping a Python object."""

    def __init__(self, name: str, methods: dict[str, Any] | None = None, value: Any = None):
        self.name = name
        self.methods = methods or {}
        self.value = value
        self.calls: list[tuple[str, tuple]] = []

    def invoke(self, method: str, *args: Any) -> Any:
        self.calls.append((method, args))
        return self.methods[method](*args)


class _FakeIRIS:
    """Records classMethodValue calls; %SYS.Python.Import returns a module from `modules`."""

    def __init__(self, fail: set[str] | None = None):
        self.fail = fail or set()
        self.imports: list[str] = []
        self.class_calls: list[tuple] = []
        self.meminfo_file = _FakePyObject(
            "file", {"read": lambda: MEMINFO, "close": lambda: None}
        )
        self.modules = {
            "platform": _FakePyObject(
                "platform",
                {
                    "python_version": lambda: "3.12.3",
                    "platform": lambda: "Linux-test-x86_64",
                    "node": lambda: "iris-host",
                },
            ),
            "os": _FakePyObject(
                "os",
                {
                    "cpu_count": lambda: 8,
                    "getloadavg": lambda: _FakePyObject("tuple", value=[0.5, 0.25, 0.125]),
                    "getpid": lambda: 10910,
                },
            ),
            "json": _FakePyObject("json", {"dumps": lambda obj: json.dumps(obj.value)}),
            "shutil": _FakePyObject(
                "shutil", {"disk_usage": lambda path: _FakePyObject("usage", value=[1000, 400, 600])}
            ),
            "builtins": _FakePyObject(
                "builtins",
                {
                    "open": lambda path: self.meminfo_file,
                    "list": lambda obj: _FakePyObject("list", value=obj.value),
                    "len": lambda obj: len(obj.value),
                },
            ),
            "importlib.metadata": _FakePyObject(
                "importlib.metadata", {"distributions": lambda: _FakePyObject("gen", value=list(range(55)))}
            ),
        }

    def classMethodValue(self, class_name: str, method: str, *args: Any) -> Any:
        self.class_calls.append((class_name, method, *args))
        if (class_name, method) == ("%SYS.Python", "Import"):
            (module,) = args
            self.imports.append(module)
            if module in self.fail:
                raise RuntimeError(f"<PYTHON EXCEPTION> import {module}")
            return self.modules[module]
        if (class_name, method) == ("%SYSTEM.Util", "ManagerDirectory"):
            return "/usr/irissys/mgr/"
        raise AssertionError(f"unexpected class method {class_name}.{method}")


def _diagnostics(fake: _FakeIRIS) -> EmbeddedPythonDiagnostics:
    diagnostics = EmbeddedPythonDiagnostics(get_settings())
    diagnostics._iris = fake  # so _ensure_connected() doesn't connect
    return diagnostics


def test_collect_returns_every_value_from_embedded_python() -> None:
    result = _diagnostics(_FakeIRIS()).collect_sync()

    assert result.python_version == "3.12.3"
    assert result.platform == "Linux-test-x86_64"
    assert result.hostname == "iris-host"
    assert result.cpu_count == 8
    assert result.load_average == [0.5, 0.25, 0.125]
    assert result.iris_pid == 10910
    assert result.manager_directory == "/usr/irissys/mgr/"
    assert result.manager_disk.model_dump() == {"total_bytes": 1000, "used_bytes": 400, "free_bytes": 600}
    assert result.memory.total_bytes == 8017536 * 1024
    assert result.memory.available_bytes == 6511168 * 1024
    assert result.package_count == 55
    assert result.unavailable == []
    assert result.duration_ms >= 0


def test_only_fixed_stdlib_modules_and_class_methods_are_used() -> None:
    fake = _FakeIRIS()
    _diagnostics(fake).collect_sync()

    assert set(fake.imports) <= {"platform", "os", "json", "shutil", "builtins", "importlib.metadata"}
    assert {call[:2] for call in fake.class_calls} == {
        ("%SYS.Python", "Import"),
        ("%SYSTEM.Util", "ManagerDirectory"),
    }
    assert fake.modules["builtins"].calls[0] == ("open", ("/proc/meminfo",))
    assert fake.meminfo_file.calls == [("read", ()), ("close", ())]


def test_a_failing_probe_is_reported_unavailable_without_failing_the_rest() -> None:
    result = _diagnostics(_FakeIRIS(fail={"shutil"})).collect_sync()

    assert result.manager_disk is None
    assert result.unavailable == ["manager_disk"]
    assert result.python_version == "3.12.3"
    assert result.memory is not None


def test_meminfo_file_is_closed_even_when_parsing_fails() -> None:
    fake = _FakeIRIS()
    fake.meminfo_file.methods["read"] = lambda: "garbage"
    result = _diagnostics(fake).collect_sync()

    assert result.memory is None
    assert "memory" in result.unavailable
    assert ("close", ()) in fake.meminfo_file.calls


def test_connection_failure_raises_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    diagnostics = EmbeddedPythonDiagnostics(get_settings())

    def refuse() -> None:
        raise ConnectionRefusedError("iris.invalid.test:1973")

    monkeypatch.setattr(diagnostics, "_ensure_connected", refuse)
    with pytest.raises(EmbeddedPythonUnavailableError):
        diagnostics.collect_sync()


def test_every_probe_failing_raises_and_drops_the_connection() -> None:
    fake = _FakeIRIS()
    fake.classMethodValue = lambda *args: (_ for _ in ()).throw(RuntimeError("connection lost"))
    diagnostics = _diagnostics(fake)

    with pytest.raises(EmbeddedPythonUnavailableError):
        diagnostics.collect_sync()
    assert diagnostics._iris is None


def test_parse_meminfo_without_mem_available() -> None:
    memory = parse_meminfo("MemTotal: 1024 kB\n")
    assert memory.total_bytes == 1024 * 1024
    assert memory.available_bytes is None
    with pytest.raises(ValueError):
        parse_meminfo("MemFree: 1 kB\n")


# --- route ---


class _StubDiagnostics:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.ran_on_event_loop: bool | None = None

    def collect_sync(self) -> PythonDiagnostics:
        try:
            asyncio.get_running_loop()
            self.ran_on_event_loop = True
        except RuntimeError:
            self.ran_on_event_loop = False
        if self.fail:
            raise EmbeddedPythonUnavailableError()
        return _diagnostics(_FakeIRIS()).collect_sync()


@pytest.fixture
def stub_client():
    def make(stub: _StubDiagnostics) -> TestClient:
        app.dependency_overrides[get_python_diagnostics] = lambda: stub
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


def test_route_returns_diagnostics_collected_off_the_event_loop(stub_client) -> None:
    stub = _StubDiagnostics()
    response = stub_client(stub).get("/api/iris/python/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["python_version"] == "3.12.3"
    assert body["iris_pid"] == 10910
    assert body["manager_disk"]["free_bytes"] == 600
    assert stub.ran_on_event_loop is False


def test_route_failure_is_a_safe_502(stub_client) -> None:
    response = stub_client(_StubDiagnostics(fail=True)).get("/api/iris/python/diagnostics")

    assert response.status_code == 502
    assert response.json() == {"detail": "Could not run Embedded Python diagnostics in IRIS"}
    assert "test-password-not-real" not in response.text


def test_route_is_get_only(stub_client) -> None:
    response = stub_client(_StubDiagnostics()).post("/api/iris/python/diagnostics")
    assert response.status_code == 405
