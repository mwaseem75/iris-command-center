"""Optional, feature-flagged persistence of ExecutionTrace records into the
existing IRIS instance — additive to, and never a replacement for, the
in-memory store (app/observability/store.py), which remains the only thing
GET /api/iris/observability/traces ever reads from.

Off by default (Settings.persist_traces_to_iris). When on, every trace
app/observability/store.py's record_trace() already records in-memory is
ALSO, best-effort, written to a single IRIS global — ^CommandCenterTrace,
in the configured namespace (default: USER) — via IRIS's Native API
(`intersystems-irispython`, the one new dependency this feature adds). No
new IRIS class, table, or web application is created; a global is the
smallest persistent unit IRIS has.

Global shape (newest-first is reconstructed by the highest seq, mirroring
store.py's deque(maxlen=...) semantics):
    ^CommandCenterTrace("seq")            = the highest sequence number used so far
    ^CommandCenterTrace("trace", <seq>)   = that trace's ExecutionTrace.model_dump_json()

Capped at _MAX_IRIS_TRACES (200, matching store.py's own _MAX_TRACES): once
more than 200 traces have been written, the oldest (lowest surviving seq)
is killed on every subsequent write, the same "newest evicts oldest"
policy store.py already uses for its deque.

Safety:
- persist_sync() NEVER raises — any connection/write failure is logged and
  swallowed, so a misconfigured or unreachable IRIS instance can only ever
  degrade this feature back to "in-memory only, like before this file
  existed" — it can never fail or slow down an operation attempt, and it
  has no code path to any IRIS admin endpoint or the operations registry
  (app/authorization/operations.py). This is telemetry about attempts,
  not a gated business operation, so it deliberately does not go through
  OperationExecutor/authorize().
- persist_sync() only ever writes the exact same ExecutionTrace JSON
  already proven free of credential-shaped substrings (see
  tests/test_observability.py's test_trace_never_contains_forbidden_
  sensitive_substrings) — no new/hand-built payload is introduced here.
- persist_sync() is BLOCKING (the Native API driver is synchronous). It
  must only ever be called off the event loop thread — see
  app/observability/store.py's use of run_in_executor — never awaited or
  called directly from async code.
- The `iris` package is imported lazily, inside _ensure_connected(), so
  this module — and therefore app/observability/store.py, which imports
  IRISTraceWriter's type for annotations only — can be imported and
  exercised in tests without the optional dependency installed, as long as
  the feature flag stays off (the default).
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
    """One instance is created at app startup (see app/main.py's lifespan)
    only when Settings.persist_traces_to_iris is True. Connecting to IRIS
    is deferred to the first persist_sync() call (mirrors
    app/auth/iris_auth.py's own lazy-session pattern) — constructing this
    class makes no network call."""

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
        """Blocking. Writes `trace` to ^CommandCenterTrace and evicts the
        oldest entry once more than _MAX_IRIS_TRACES exist. Never raises —
        see module docstring's Safety section."""
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

    def close(self) -> None:
        """Best-effort connection close, called from app/main.py's lifespan
        shutdown. Never raises."""
        if self._connection is None:
            return
        try:
            self._connection.close()
        except Exception:  # noqa: BLE001 - shutdown must never crash on this
            logger.warning("Error closing IRIS trace persistence connection.", exc_info=True)
        finally:
            self._connection = None
            self._iris = None
