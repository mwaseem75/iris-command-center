"""Tests for the read-only Message Log: parsing IRIS's messages.log, reading
its tail through Embedded Python (a fake Native API) and the GET route."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_python_diagnostics
from app.embedded_python import messages_log
from app.embedded_python.diagnostics import EmbeddedPythonDiagnostics, EmbeddedPythonUnavailableError
from app.embedded_python.messages_log import MessageLog, MessageLogEntry, parse_messages_log
from app.main import app

SAMPLE = (
    "09/28/26-01:46:19:123 (465) 0 [Utility.Event] Journal switched\n"
    "09/28/26-01:46:20:004 (472) 1 [Generic.Event] Warning: Alternate and primary journal directories are the same\n"
    "09/28/26-01:46:21:500 (480) 0 [Utility.Event] INTERSYSTEMS IRIS JOURNALING SYSTEM MESSAGE\n"
    "Journaling started to: /usr/irissys/mgr/journal/20260928.006\n"
    "09/28/26-01:47:00:001 (491) 2 Severe error without a source\n"
    "09/28/26-01:48:00:000 (500) 3 [System.Fatal] Fatal thing\n"
)


# --- parsing ---


def test_parses_entries_newest_first() -> None:
    entries, capped = parse_messages_log(SAMPLE)

    assert not capped
    assert [e.pid for e in entries] == [500, 491, 480, 472, 465]
    assert entries[-1] == MessageLogEntry(timestamp="09/28/26-01:46:19:123", pid=465, level=0, level_name="Info",
                                          source="Utility.Event", message="Journal switched")
    assert [e.level_name for e in entries] == ["Fatal", "Severe", "Info", "Warning", "Info"]


def test_continuation_lines_join_the_previous_entry() -> None:
    entries, _ = parse_messages_log(SAMPLE)
    journal = next(e for e in entries if e.pid == 480)
    assert journal.message == ("INTERSYSTEMS IRIS JOURNALING SYSTEM MESSAGE\n"
                               "Journaling started to: /usr/irissys/mgr/journal/20260928.006")


def test_an_entry_without_a_source_keeps_its_message() -> None:
    entries, _ = parse_messages_log(SAMPLE)
    severe = next(e for e in entries if e.pid == 491)
    assert severe.source is None and severe.message == "Severe error without a source"


def test_a_cut_off_first_fragment_is_skipped_not_invented() -> None:
    text = "tail of an older message\nmore of it\n" + SAMPLE
    entries, _ = parse_messages_log(text)
    assert len(entries) == 5
    assert all(e.timestamp and e.pid for e in entries)
    assert "tail of an older message" not in "".join(e.message for e in entries)


def test_entries_are_capped_to_the_newest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(messages_log, "MAX_ENTRIES", 2)
    entries, capped = parse_messages_log(SAMPLE)
    assert capped and [e.pid for e in entries] == [500, 491]


def test_empty_log_has_no_entries() -> None:
    assert parse_messages_log("") == ([], False)


# --- reading the tail through Embedded Python (fake Native API) ---


class _FakeFile:
    def __init__(self, data: bytes, fail_read: bool = False):
        self.data = data
        self.position = 0
        self.closed = False
        self.fail_read = fail_read
        self.calls: list[tuple] = []

    def invoke(self, method: str, *args: Any) -> Any:
        self.calls.append((method, *args))
        if method == "seek":
            offset, whence = (args + (0,))[:2]
            self.position = len(self.data) + offset if whence == 2 else offset
            return self.position
        if method == "read":
            if self.fail_read:
                raise RuntimeError("read failed")
            return self.data[self.position:]
        if method == "close":
            self.closed = True
            return None
        raise AssertionError(f"unexpected file method {method}")


class _FakeModule:
    def __init__(self, name: str, fake: "_FakeNative"):
        self.name = name
        self.fake = fake

    def invoke(self, method: str, *args: Any) -> Any:
        self.fake.module_calls.append((self.name, method, args))
        if (self.name, method) == ("os.path", "join"):
            return "/".join(part.rstrip("/") for part in args)
        if (self.name, method) == ("builtins", "open"):
            return self.fake.file
        raise AssertionError(f"unexpected call {self.name}.{method}")


class _FakeNative:
    def __init__(self, data: bytes, **file_options: Any):
        self.file = _FakeFile(data, **file_options)
        self.module_calls: list[tuple] = []
        self.class_calls: list[tuple] = []

    def classMethodValue(self, class_name: str, method: str, *args: Any) -> Any:  # noqa: N802 - Native API name
        self.class_calls.append((class_name, method, args))
        if (class_name, method) == ("%SYSTEM.Util", "ManagerDirectory"):
            return "/usr/irissys/mgr/"
        if (class_name, method) == ("%SYS.Python", "Import"):
            return _FakeModule(args[0], self)
        raise AssertionError(f"unexpected class method {class_name}.{method}")


def _reader(fake: _FakeNative) -> EmbeddedPythonDiagnostics:
    from app.config import Settings

    reader = EmbeddedPythonDiagnostics(Settings(iris_base_url="http://iris.invalid.test:52773", iris_username="u",
                                                iris_password="test-password-not-real"))
    reader._iris = fake  # skip the real connection
    return reader


def test_reads_the_fixed_messages_log_path_read_only() -> None:
    fake = _FakeNative(SAMPLE.encode())

    log = _reader(fake).read_messages_log_sync()

    assert log.path == "/usr/irissys/mgr/messages.log"
    assert ("builtins", "open", ("/usr/irissys/mgr/messages.log", "rb")) in fake.module_calls
    assert {name for name, _, _ in fake.module_calls} == {"os.path", "builtins"}
    assert {(c, m) for c, m, _ in fake.class_calls} == {("%SYSTEM.Util", "ManagerDirectory"), ("%SYS.Python", "Import")}
    assert fake.file.closed
    assert not log.truncated and log.size_bytes == log.read_bytes == len(SAMPLE.encode())
    assert [e.pid for e in log.entries] == [500, 491, 480, 472, 465]


def test_only_the_tail_of_a_large_log_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.embedded_python import diagnostics

    monkeypatch.setattr(diagnostics, "TAIL_BYTES", 150)
    data = SAMPLE.encode()
    fake = _FakeNative(data)

    log = _reader(fake).read_messages_log_sync()

    assert ("seek", len(data) - 150) in fake.file.calls
    assert log.truncated and log.read_bytes == 150 and log.size_bytes == len(data)
    assert log.entries and all(e.timestamp for e in log.entries)  # the cut-off fragment was skipped


def test_the_file_is_closed_and_the_error_is_safe_when_reading_fails() -> None:
    fake = _FakeNative(b"x", fail_read=True)
    with pytest.raises(EmbeddedPythonUnavailableError):
        _reader(fake).read_messages_log_sync()
    assert fake.file.closed


def test_undecodable_bytes_are_replaced_not_fatal() -> None:
    data = SAMPLE.encode() + b"09/28/26-02:00:00:000 (600) 0 [Utility.Event] bad \xff byte\n"
    log = _reader(_FakeNative(data)).read_messages_log_sync()
    assert log.entries[0].pid == 600 and "�" in log.entries[0].message


# --- the route ---


class _StubReader:
    def __init__(self, *, fail: bool = False):
        self.fail = fail

    def read_messages_log_sync(self) -> MessageLog:
        if self.fail:
            raise EmbeddedPythonUnavailableError()
        entries, _ = parse_messages_log(SAMPLE)
        return MessageLog(path="/usr/irissys/mgr/messages.log", size_bytes=10, read_bytes=10, truncated=False,
                          entries=entries, duration_ms=1.0)


@pytest.fixture
def stub_client():
    def make(stub: _StubReader) -> TestClient:
        app.dependency_overrides[get_python_diagnostics] = lambda: stub
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


def test_route_returns_the_newest_entries(stub_client) -> None:
    response = stub_client(_StubReader()).get("/api/iris/messages-log")
    assert response.status_code == 200
    body = response.json()
    assert [e["pid"] for e in body["entries"]] == [500, 491, 480, 472, 465]
    assert set(body["entries"][0]) == {"timestamp", "pid", "level", "level_name", "source", "message"}


def test_route_failure_is_a_safe_502(stub_client) -> None:
    response = stub_client(_StubReader(fail=True)).get("/api/iris/messages-log")
    assert response.status_code == 502
    assert response.json() == {"detail": "Could not read IRIS's messages.log"}


def test_route_is_get_only_and_takes_no_path_input(stub_client) -> None:
    client = stub_client(_StubReader())
    for method in ("post", "put", "delete", "patch"):
        assert getattr(client, method)("/api/iris/messages-log").status_code == 405
    # Query parameters can't choose what is read: they're ignored.
    assert client.get("/api/iris/messages-log", params={"path": "/etc/passwd"}).json()["entries"][0]["pid"] == 500
