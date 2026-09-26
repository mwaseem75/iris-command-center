"""Optionally saves execution traces to IRIS so they survive a restart.

Off by default (PERSIST_TRACES_TO_IRIS). When on, every trace that
store.record_trace() keeps in memory is also written, best effort, to the
^CommandCenterTrace global in the configured namespace (USER by default)
over the Native API. The API still reads traces from the in-memory store.

Global layout:
    ^CommandCenterTrace("seq")          = last sequence number used
    ^CommandCenterTrace("trace", <seq>) = the trace as JSON

Only the newest _MAX_IRIS_TRACES (200, same as the in-memory store) are
kept; each write past that deletes the oldest.

Notes:
- persist_sync() never raises. If IRIS is unreachable we log it and carry
  on with memory only; an operation never fails because of this.
- It writes the same trace JSON the API returns, which is already
  checked to contain no credentials (see test_observability.py).
- The driver is synchronous, so call this from a thread (store.py uses
  run_in_executor), never directly from async code.
- `iris` is imported lazily, so tests run fine without it as long as the
  feature stays off.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

from app.config import Settings
from app.observability.models import ExecutionTrace

logger = logging.getLogger(__name__)

_GLOBAL_NAME = "CommandCenterTrace"
_MAX_IRIS_TRACES = 200


class IRISTraceWriter:
    """Created in app/main.py only when persist_traces_to_iris is on. Doesn't
    connect until the first persist_sync() call.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._connection: Any = None
        self._iris: Any = None

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

    def persist_sync(self, trace: ExecutionTrace) -> None:
        """Blocking. Write `trace` to ^CommandCenterTrace and drop the oldest entry
        once there are more than _MAX_IRIS_TRACES. Never raises.
        """
        try:
            self._ensure_connected()

            raw_seq = self._iris.get(_GLOBAL_NAME, "seq")
            seq = (int(raw_seq) if raw_seq else 0) + 1
            self._iris.set(str(seq), _GLOBAL_NAME, "seq")
            self._iris.set(trace.model_dump_json(), _GLOBAL_NAME, "trace", seq)

            oldest_surviving_seq = seq - _MAX_IRIS_TRACES
            if oldest_surviving_seq >= 1:
                self._iris.kill(_GLOBAL_NAME, "trace", oldest_surviving_seq)
        except Exception:  # noqa: BLE001 - a persistence failure must never surface
            logger.warning(
                "Could not persist execution trace %s to IRIS (^%s) — the "
                "in-memory trace store is unaffected.",
                trace.trace_id,
                _GLOBAL_NAME,
                exc_info=True,
            )

    def load_recent_sync(self, limit: int = _MAX_IRIS_TRACES) -> list[ExecutionTrace]:
        """Blocking. Read up to `limit` of the newest saved traces, newest first.
        Used once at startup to fill the in-memory store.

        Walks down from "seq" and skips missing or broken entries. Never raises:
        on an error it returns what it has so far (usually []).
        """
        traces: list[ExecutionTrace] = []
        try:
            self._ensure_connected()

            raw_seq = self._iris.get(_GLOBAL_NAME, "seq")
            seq = int(raw_seq) if raw_seq else 0
            lowest = max(1, seq - min(limit, _MAX_IRIS_TRACES) + 1)
            for current in range(seq, lowest - 1, -1):
                raw = self._iris.get(_GLOBAL_NAME, "trace", current)
                if not raw:
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                try:
                    traces.append(ExecutionTrace.model_validate_json(raw))
                except ValueError:
                    logger.warning(
                        "Skipping unreadable persisted execution trace ^%s(\"trace\",%d).",
                        _GLOBAL_NAME,
                        current,
                    )
        except Exception:  # noqa: BLE001 - hydration failure must never block startup
            logger.warning(
                "Could not load persisted execution traces from IRIS (^%s) — "
                "starting with %d loaded.",
                _GLOBAL_NAME,
                len(traces),
                exc_info=True,
            )
        return traces

    def close(self) -> None:
        """Close the connection at shutdown, ignoring errors."""
        if self._connection is None:
            return
        try:
            self._connection.close()
        except Exception:  # noqa: BLE001 - shutdown must never crash on this
            logger.warning("Error closing IRIS trace persistence connection.", exc_info=True)
        finally:
            self._connection = None
            self._iris = None
