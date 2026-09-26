"""Read-only host diagnostics computed by Embedded Python running INSIDE the
connected IRIS instance — the values come from IRIS's own Python runtime
(%SYS.Python), not from this backend's host.

Transport: IRIS's Native API (`intersystems-irispython`), the same driver
and the same lazy-connection pattern app/observability/iris_trace_writer.py
already uses (superserver port + namespace from Settings). No new IRIS
class, table, global, web application or Python package is created or
required — everything below is a built-in Python stdlib module imported
through the built-in %SYS.Python.Import() class method.

Safety:
- FIXED CALLS ONLY. Every module name, method name and argument used here
  is a literal in this file (see _PROBES). collect_sync() takes no input,
  so no caller-supplied text can ever reach %SYS.Python.Import() or
  IRISObject.invoke() — which together could otherwise run arbitrary
  Python inside IRIS.
- READ-ONLY. Every call only reads process/host state (versions, CPU
  count, load average, disk usage, /proc/meminfo, installed package
  metadata); nothing writes to disk, IRIS, or any global.
- BLOCKING. The Native API driver is synchronous, so collect_sync() must
  only run off the event loop (see app/routes/python.py's run_in_executor),
  and a lock serializes use of the single, non-thread-safe connection.
- GRACEFUL. A failing individual probe yields a null field (listed in
  `unavailable`) rather than an error; only an unreachable IRIS — or every
  probe failing — raises EmbeddedPythonUnavailableError, which the route
  turns into a fixed, credential-free 502 message.
- The `iris` package is imported lazily, so this module can be imported
  and tested without a live IRIS instance.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from app.config import Settings

logger = logging.getLogger(__name__)


class EmbeddedPythonUnavailableError(Exception):
    """IRIS (or its Embedded Python runtime) could not be reached. Never
    carries connection details or credentials."""


class DiskUsage(BaseModel):
    total_bytes: int
    used_bytes: int
    free_bytes: int


class HostMemory(BaseModel):
    total_bytes: int
    available_bytes: int | None = None


class PythonDiagnostics(BaseModel):
    """Every field is nullable: a probe that fails is reported as null and
    named in `unavailable` — values are never guessed or defaulted."""

    python_version: str | None = None
    platform: str | None = None
    hostname: str | None = None
    cpu_count: int | None = None
    load_average: list[float] | None = None
    iris_pid: int | None = None
    manager_directory: str | None = None
    manager_disk: DiskUsage | None = None
    memory: HostMemory | None = None
    package_count: int | None = None
    unavailable: list[str] = Field(default_factory=list)
    duration_ms: float


def _import(db: Any, module: str) -> Any:
    return db.classMethodValue("%SYS.Python", "Import", module)


def _to_json(db: Any, value: Any) -> Any:
    """Tuples/named tuples come back over the Native API as opaque object
    handles, so they are serialized inside IRIS and parsed here."""
    raw = _import(db, "json").invoke("dumps", value)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def _text(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def parse_meminfo(text: str) -> HostMemory:
    """Parses /proc/meminfo's `MemTotal`/`MemAvailable` (reported in kB)."""
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if key in ("MemTotal", "MemAvailable") and parts:
            values[key] = int(parts[0]) * 1024
    if "MemTotal" not in values:
        raise ValueError("MemTotal not found in /proc/meminfo")
    return HostMemory(total_bytes=values["MemTotal"], available_bytes=values.get("MemAvailable"))


def _manager_disk(db: Any) -> DiskUsage:
    directory = _text(db.classMethodValue("%SYSTEM.Util", "ManagerDirectory"))
    total, used, free = _to_json(db, _import(db, "shutil").invoke("disk_usage", directory))
    return DiskUsage(total_bytes=total, used_bytes=used, free_bytes=free)


def _host_memory(db: Any) -> HostMemory:
    # pathlib.Path objects are converted to plain strings over the Native
    # API, so the file is opened, read and explicitly closed instead.
    handle = _import(db, "builtins").invoke("open", "/proc/meminfo")
    try:
        return parse_meminfo(_text(handle.invoke("read")))
    finally:
        handle.invoke("close")


def _package_count(db: Any) -> int:
    builtins = _import(db, "builtins")
    distributions = _import(db, "importlib.metadata").invoke("distributions")
    return int(builtins.invoke("len", builtins.invoke("list", distributions)))


# The complete, fixed set of calls this module can make: (field, probe).
_PROBES: tuple[tuple[str, Callable[[Any], Any]], ...] = (
    ("python_version", lambda db: _text(_import(db, "platform").invoke("python_version"))),
    ("platform", lambda db: _text(_import(db, "platform").invoke("platform"))),
    ("hostname", lambda db: _text(_import(db, "platform").invoke("node"))),
    ("cpu_count", lambda db: int(_import(db, "os").invoke("cpu_count"))),
    ("load_average", lambda db: [float(v) for v in _to_json(db, _import(db, "os").invoke("getloadavg"))]),
    ("iris_pid", lambda db: int(_import(db, "os").invoke("getpid"))),
    ("manager_directory", lambda db: _text(db.classMethodValue("%SYSTEM.Util", "ManagerDirectory"))),
    ("manager_disk", _manager_disk),
    ("memory", _host_memory),
    ("package_count", _package_count),
)


class EmbeddedPythonDiagnostics:
    """One instance is created at app startup (see app/main.py's lifespan).
    Constructing it makes no network call; the Native API connection is
    opened on first use and reused, mirroring IRISTraceWriter."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._connection: Any = None
        self._iris: Any = None
        self._lock = threading.Lock()

    def _ensure_connected(self) -> None:
        if self._iris is not None:
            return

        import iris  # noqa: PLC0415 - deliberately lazy; see module docstring

        hostname = urlsplit(self._settings.iris_base_url).hostname
        self._connection = iris.connect(
            hostname,
            self._settings.iris_superserver_port,
            self._settings.iris_namespace,
            self._settings.iris_username,
            self._settings.iris_password.get_secret_value(),
        )
        self._iris = iris.createIRIS(self._connection)

    def _reset(self) -> None:
        """Drops a possibly broken connection so the next call reconnects."""
        connection, self._connection, self._iris = self._connection, None, None
        if connection is not None:
            try:
                connection.close()
            except Exception:  # noqa: BLE001 - already failing; just discard it
                pass

    def collect_sync(self) -> PythonDiagnostics:
        """Blocking. Runs every probe in _PROBES inside IRIS's Embedded
        Python. Raises EmbeddedPythonUnavailableError only if IRIS can't be
        reached or every probe fails."""
        with self._lock:
            started = time.perf_counter()
            try:
                self._ensure_connected()
            except Exception as exc:  # noqa: BLE001 - never leak connection details
                logger.warning("Could not connect to IRIS for Embedded Python diagnostics.", exc_info=True)
                self._reset()
                raise EmbeddedPythonUnavailableError() from exc

            values: dict[str, Any] = {}
            unavailable: list[str] = []
            for field, probe in _PROBES:
                try:
                    values[field] = probe(self._iris)
                except Exception:  # noqa: BLE001 - one failing probe must not fail the rest
                    logger.warning("Embedded Python diagnostic %r failed.", field, exc_info=True)
                    unavailable.append(field)

            if not values:
                self._reset()
                raise EmbeddedPythonUnavailableError()

            return PythonDiagnostics(
                **values,
                unavailable=unavailable,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )

    def close(self) -> None:
        """Best-effort connection close, called from app/main.py's lifespan
        shutdown. Never raises."""
        with self._lock:
            self._reset()
