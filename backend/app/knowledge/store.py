"""IRIS-backed persistence and vector search for the knowledge corpus
(app/knowledge/corpus.py), embedded by app/knowledge/embedding.py.

Off by default (Settings.enable_knowledge_search). When on:

- Startup (app/main.py's lifespan) calls ensure_indexed_sync(), which
  creates the table below in Settings.iris_namespace (default USER, whose
  data lives in the persistent USER database) if it does not exist yet,
  then deterministically reindexes it: every row is deleted and the full
  corpus re-inserted, in corpus order, in one explicit transaction
  (autocommit is off only for its duration; any failure rolls back to the
  previous rows). The corpus and
  embedder are both deterministic, so every reindex writes identical rows —
  a recreated backend or IRIS container needs no manual setup.
- GET /api/iris/knowledge/search runs search_sync(): the query is embedded
  here and compared inside IRIS with VECTOR_COSINE, TOP 5.

    CREATE TABLE CommandCenter.Knowledge (
        Source    VARCHAR(200)  -- KnowledgeDocument.doc_id, e.g. "operation:database.mount"
        Title     VARCHAR(500)
        Body      VARCHAR(4000)
        Embedding VECTOR(DOUBLE, 256)
    )

Vectors are stored only in IRIS — never on the backend filesystem.

Safety:
- Every value reaches IRIS as a bound SQL parameter (?) — including the
  query's vector literal; no caller text is ever interpolated into SQL.
- The only writes are to CommandCenter.Knowledge, the table this module
  owns (DDL once, then DELETE/INSERT of public corpus data). Nothing else
  in IRIS is touched, and the table holds no credentials or secrets.
- BLOCKING (DB-API over the Native API driver) — call only off the event
  loop. A lock serializes use of the single connection.
- GRACEFUL: an unreachable IRIS (or any SQL failure) raises
  KnowledgeStoreUnavailableError, which the route turns into a fixed 502
  and startup logs and ignores. A failure also drops the connection and
  marks the store unindexed, so the next search reconnects and re-ensures
  the table (e.g. after an IRIS container was recreated).
- The `iris` package is imported lazily, so this module can be imported
  and tested without it.
"""

from __future__ import annotations

import logging
import threading
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel

from app.config import Settings
from app.knowledge.corpus import KnowledgeDocument, build_corpus
from app.knowledge.embedding import DIMENSIONS, embed

logger = logging.getLogger(__name__)

SCHEMA = "CommandCenter"
TABLE = "Knowledge"
_QUALIFIED = f"{SCHEMA}.{TABLE}"
SOURCE_MAX = 200
TITLE_MAX = 500
BODY_MAX = 4000
TOP_K = 5

_TABLE_EXISTS_SQL = "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?"
_CREATE_SQL = (
    f"CREATE TABLE {_QUALIFIED} ("
    f"Source VARCHAR({SOURCE_MAX}) NOT NULL, "
    f"Title VARCHAR({TITLE_MAX}) NOT NULL, "
    f"Body VARCHAR({BODY_MAX}) NOT NULL, "
    f"Embedding VECTOR(DOUBLE, {DIMENSIONS}) NOT NULL)"
)
_DELETE_SQL = f"DELETE FROM {_QUALIFIED}"
_INSERT_SQL = (
    f"INSERT INTO {_QUALIFIED} (Source, Title, Body, Embedding) "
    f"VALUES (?, ?, ?, TO_VECTOR(?, DOUBLE, {DIMENSIONS}))"
)
_SEARCH_SQL = (
    f"SELECT TOP {TOP_K} Source, Title, Body, "
    f"VECTOR_COSINE(Embedding, TO_VECTOR(?, DOUBLE, {DIMENSIONS})) AS Score "
    f"FROM {_QUALIFIED} ORDER BY Score DESC, Source"
)


class KnowledgeStoreUnavailableError(Exception):
    """IRIS could not be reached or the SQL failed. Never carries
    connection details or credentials."""


class KnowledgeHit(BaseModel):
    source: str
    title: str
    body: str
    score: float


class KnowledgeSearchResponse(BaseModel):
    query: str
    results: list[KnowledgeHit]


def vector_literal(vector: list[float]) -> str:
    """TO_VECTOR's comma-separated input. Fixed-point formatting, so no
    value is ever written in exponent notation."""
    return ",".join(f"{value:.12f}" for value in vector)


def _text(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _check_fits(doc: KnowledgeDocument) -> None:
    if len(doc.doc_id) > SOURCE_MAX or len(doc.title) > TITLE_MAX or len(doc.body) > BODY_MAX:
        raise ValueError(f"Knowledge document {doc.doc_id!r} exceeds the table's column sizes")


class IRISKnowledgeStore:
    """One instance is created at app startup, only when
    Settings.enable_knowledge_search is True. Constructing it makes no
    network call; the connection opens on first use (mirrors
    IRISTraceWriter / EmbeddedPythonDiagnostics)."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._connection: Any = None
        self._indexed = False
        self._lock = threading.Lock()

    def _ensure_connected(self) -> None:
        if self._connection is not None:
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

    def _reset(self) -> None:
        """Drops a possibly broken connection; the next call reconnects
        and re-ensures the table."""
        connection, self._connection, self._indexed = self._connection, None, False
        if connection is not None:
            try:
                connection.close()
            except Exception:  # noqa: BLE001 - already failing; just discard it
                pass

    def _index_locked(self) -> int:
        corpus = build_corpus()
        for doc in corpus:
            _check_fits(doc)
        rows = [(doc.doc_id, doc.title, doc.body, vector_literal(embed(f"{doc.title}\n{doc.body}"))) for doc in corpus]

        self._ensure_connected()
        cursor = self._connection.cursor()
        cursor.execute(_TABLE_EXISTS_SQL, [SCHEMA, TABLE])
        if not int(cursor.fetchone()[0]):
            cursor.execute(_CREATE_SQL)
            logger.info("Created %s for knowledge search.", _QUALIFIED)
        # The driver autocommits every statement by default (verified live:
        # a failed INSERT mid-reindex otherwise leaves a partial table), so
        # the DELETE + INSERTs run as one explicit transaction. Autocommit is
        # restored afterwards, leaving search behavior unchanged.
        self._connection.setAutoCommit(False)
        try:
            cursor.execute(_DELETE_SQL)
            for row in rows:
                cursor.execute(_INSERT_SQL, list(row))
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        finally:
            self._connection.setAutoCommit(True)
        self._indexed = True
        return len(rows)

    def ensure_indexed_sync(self) -> int:
        """Blocking. Creates the table if missing and reindexes the whole
        corpus. Returns the number of documents indexed."""
        with self._lock:
            try:
                count = self._index_locked()
            except Exception as exc:  # noqa: BLE001 - never leak connection details
                logger.warning("Could not index the knowledge corpus into IRIS (%s).", _QUALIFIED, exc_info=True)
                self._reset()
                raise KnowledgeStoreUnavailableError() from exc
            logger.info("Indexed %d knowledge documents into %s.", count, _QUALIFIED)
            return count

    def search_sync(self, query: str) -> list[KnowledgeHit]:
        """Blocking. TOP 5 corpus documents by cosine similarity to
        `query`. A query with no searchable words returns [] without
        touching IRIS (its vector would be all zeros)."""
        vector = embed(query)
        if not any(vector):
            return []
        with self._lock:
            try:
                if not self._indexed:
                    self._index_locked()
                cursor = self._connection.cursor()
                cursor.execute(_SEARCH_SQL, [vector_literal(vector)])
                rows = cursor.fetchall()
            except Exception as exc:  # noqa: BLE001 - never leak connection details
                logger.warning("Knowledge search against IRIS (%s) failed.", _QUALIFIED, exc_info=True)
                self._reset()
                raise KnowledgeStoreUnavailableError() from exc
        return [
            KnowledgeHit(source=_text(source), title=_text(title), body=_text(body), score=float(score))
            for source, title, body, score in rows
        ]

    def close(self) -> None:
        """Best-effort connection close at shutdown. Never raises."""
        with self._lock:
            self._reset()
