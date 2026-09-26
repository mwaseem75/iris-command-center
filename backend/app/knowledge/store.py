"""Stores the knowledge corpus in IRIS and searches it with vector search.

On startup (when ENABLE_KNOWLEDGE_SEARCH is on) we create the
CommandCenter.Knowledge table if needed and reload the whole corpus into it.
Searches embed the query here and let IRIS rank rows with VECTOR_COSINE.

Table:
    Source    VARCHAR(200)   document id, e.g. "operation:database.mount"
    Title     VARCHAR(500)
    Body      VARCHAR(4000)
    Embedding VECTOR(DOUBLE, 256)

All values go in as bound parameters. If IRIS is unreachable we raise
KnowledgeStoreUnavailableError, drop the connection and reindex on the next
search. The iris driver is blocking, so call this off the event loop.
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
    """IRIS was unreachable or the SQL failed."""


class KnowledgeHit(BaseModel):
    source: str
    title: str
    body: str
    score: float


class KnowledgeSearchResponse(BaseModel):
    query: str
    results: list[KnowledgeHit]


def vector_literal(vector: list[float]) -> str:
    """Format a vector for TO_VECTOR (fixed-point, no exponent notation)."""
    return ",".join(f"{value:.12f}" for value in vector)


def _text(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _check_fits(doc: KnowledgeDocument) -> None:
    if len(doc.doc_id) > SOURCE_MAX or len(doc.title) > TITLE_MAX or len(doc.body) > BODY_MAX:
        raise ValueError(f"Knowledge document {doc.doc_id!r} exceeds the table's column sizes")


class IRISKnowledgeStore:
    """Created at startup when knowledge search is enabled; connects lazily."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._connection: Any = None
        self._indexed = False
        self._lock = threading.Lock()

    def _ensure_connected(self) -> None:
        if self._connection is not None:
            return

        import iris  # noqa: PLC0415 - optional dependency, imported on first use

        hostname = urlsplit(self._settings.iris_base_url).hostname
        self._connection = iris.connect(
            hostname,
            self._settings.iris_superserver_port,
            self._settings.iris_namespace,
            self._settings.iris_username,
            self._settings.iris_password.get_secret_value(),
        )

    def _reset(self) -> None:
        """Drop the connection; the next call reconnects and reindexes."""
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
        # The iris driver autocommits by default, which would leave a half-filled
        # table if an insert failed. Run the reload as one transaction instead.
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
        """Create the table if needed and reload the corpus. Returns the row count."""
        with self._lock:
            try:
                count = self._index_locked()
            except Exception as exc:  # noqa: BLE001 - don't leak connection details
                logger.warning("Could not index the knowledge corpus into IRIS (%s).", _QUALIFIED, exc_info=True)
                self._reset()
                raise KnowledgeStoreUnavailableError() from exc
            logger.info("Indexed %d knowledge documents into %s.", count, _QUALIFIED)
            return count

    def search_sync(self, query: str) -> list[KnowledgeHit]:
        """Return the top 5 matches. A query with no real words returns []."""
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
            except Exception as exc:  # noqa: BLE001 - don't leak connection details
                logger.warning("Knowledge search against IRIS (%s) failed.", _QUALIFIED, exc_info=True)
                self._reset()
                raise KnowledgeStoreUnavailableError() from exc
        return [
            KnowledgeHit(source=_text(source), title=_text(title), body=_text(body), score=float(score))
            for source, title, body, score in rows
        ]

    def close(self) -> None:
        """Close the connection at shutdown."""
        with self._lock:
            self._reset()
