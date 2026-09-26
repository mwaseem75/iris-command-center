"""Host diagnostics collected by Embedded Python inside IRIS.

The values come from IRIS's own Python runtime (%SYS.Python), not from the
backend machine. We connect with the iris Native API driver and only call
stdlib modules through %SYS.Python.Import().

Every module, method and argument is hard-coded in _PROBES, and
collect_sync() takes no input, so nothing from a request can decide what
Python runs inside IRIS. All probes only read state. A failing probe just
leaves its field null; we only raise if IRIS is unreachable or every probe
fails. The driver is blocking, so run this off the event loop.
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
    """IRIS or its Embedded Python couldn't be reached."""


class DiskUsage(BaseModel):
    total_bytes: int
    used_bytes: int
    free_bytes: int


class HostMemory(BaseModel):
    total_bytes: int
    available_bytes: int | None = None


class PythonDiagnostics(BaseModel):
    """All fields are optional; a failed probe is null and listed in `unavailable`."""

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
    """Tuples come back as opaque handles, so serialize them to JSON inside IRIS."""
    raw = _import(db, "json").invoke("dumps", value)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def _text(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def parse_meminfo(text: str) -> HostMemory:
    """Read MemTotal and MemAvailable (kB) from /proc/meminfo."""
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
    # pathlib.Path comes back as a plain string over the Native API, so
    # open, read and close the file ourselves.
    handle = _import(db, "builtins").invoke("open", "/proc/meminfo")
    try:
        return parse_meminfo(_text(handle.invoke("read")))
    finally:
        handle.invoke("close")


def _package_count(db: Any) -> int:
    builtins = _import(db, "builtins")
    distributions = _import(db, "importlib.metadata").invoke("distributions")
    return int(builtins.invoke("len", builtins.invoke("list", distributions)))


# Every call this module can make: (field, probe).
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
    """Created at startup; the Native API connection opens on first use."""

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
        """Drop the connection so the next call reconnects."""
        connection, self._connection, self._iris = self._connection, None, None
        if connection is not None:
            try:
                connection.close()
            except Exception:  # noqa: BLE001 - already failing; just discard it
                pass

    def collect_sync(self) -> PythonDiagnostics:
        """Run all probes inside IRIS. Raises only if IRIS is unreachable or every probe fails."""
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
        """Close the connection at shutdown."""
        with self._lock:
            self._reset()
