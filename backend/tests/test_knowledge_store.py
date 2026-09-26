"""Tests for the IRIS-backed knowledge store (app/knowledge/store.py),
GET /api/iris/knowledge/search and the startup indexing wired into
app/main.py's lifespan. No test here contacts IRIS — the `iris` driver is
always replaced by a fake DB-API connection that records every statement."""

import asyncio
import sys
import types
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.dependencies import get_knowledge_store
from app.knowledge.corpus import build_corpus
from app.knowledge.embedding import embed
from app.knowledge.store import (
    BODY_MAX,
    SOURCE_MAX,
    TITLE_MAX,
    IRISKnowledgeStore,
    KnowledgeHit,
    KnowledgeStoreUnavailableError,
    vector_literal,
)
from app.main import app


class _FakeCursor:
    def __init__(self, conn: "_FakeConnection"):
        self.conn = conn
        self._result: list[tuple] = []

    def execute(self, sql: str, params: list | None = None) -> None:
        conn = self.conn
        conn.statements.append((sql, params))
        if conn.fail_on and conn.fail_on in sql:
            raise RuntimeError("<SQL ERROR> simulated")
        if "INFORMATION_SCHEMA.TABLES" in sql:
            self._result = [(1 if conn.table_exists else 0,)]
        elif sql.startswith("CREATE TABLE"):
            conn.table_exists = True
        elif sql.startswith("SELECT TOP"):
            self._result = list(conn.search_rows)
        elif sql.startswith("DELETE"):
            conn.pending = []
        elif sql.startswith("INSERT"):
            if conn.fail_insert_at is not None and len(conn.sql("INSERT")) == conn.fail_insert_at:
                raise RuntimeError("<SQL ERROR> SQLCODE -104 simulated")
            conn.pending = conn.pending + [tuple(params)]
        if conn.autocommit:  # like the real driver's default: every statement commits
            conn.committed = list(conn.pending)

    def fetchone(self) -> tuple:
        return self._result[0]

    def fetchall(self) -> list[tuple]:
        return self._result


class _FakeConnection:
    """Models the driver's transaction semantics: autocommit defaults to
    True; with it off, DELETE/INSERT changes stay pending until commit()
    and rollback() restores the committed rows."""

    def __init__(
        self,
        *,
        table_exists: bool = False,
        fail_on: str | None = None,
        fail_insert_at: int | None = None,
        committed: list[tuple] | None = None,
    ):
        self.table_exists = table_exists
        self.fail_on = fail_on
        self.fail_insert_at = fail_insert_at  # 1-based INSERT number that fails
        self.statements: list[tuple[str, list | None]] = []
        self.search_rows: list[tuple] = []
        self.autocommit = True
        self.autocommit_changes: list[bool] = []
        self.committed: list[tuple] = list(committed or [])
        self.pending: list[tuple] = list(self.committed)
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def setAutoCommit(self, value: bool) -> None:  # noqa: N802 - driver's own method name
        self.autocommit = value
        self.autocommit_changes.append(value)

    def commit(self) -> None:
        self.commits += 1
        self.committed = list(self.pending)

    def rollback(self) -> None:
        self.rollbacks += 1
        self.pending = list(self.committed)

    def close(self) -> None:
        self.closed = True

    def sql(self, prefix: str) -> list[tuple[str, list | None]]:
        return [s for s in self.statements if s[0].startswith(prefix)]


@pytest.fixture
def fake_iris(monkeypatch: pytest.MonkeyPatch):
    """Installs a fake `iris` module; returns the list of connections it
    handed out and the connect() arguments it received."""
    state: dict[str, Any] = {"connections": [], "args": [], "refuse": False, "kwargs": {}}

    def connect(*args: Any) -> _FakeConnection:
        state["args"].append(args)
        if state["refuse"]:
            raise ConnectionRefusedError("iris.invalid.test:1973")
        conn = _FakeConnection(**state["kwargs"])
        state["connections"].append(conn)
        return conn

    monkeypatch.setitem(sys.modules, "iris", types.SimpleNamespace(connect=connect))
    return state


def _store() -> IRISKnowledgeStore:
    return IRISKnowledgeStore(get_settings())


# --- indexing ---


def test_ensure_indexed_creates_missing_table_then_indexes_every_document(fake_iris) -> None:
    count = _store().ensure_indexed_sync()
    conn = fake_iris["connections"][0]

    corpus = build_corpus()
    assert count == len(corpus)
    (exists_sql, exists_params), = conn.sql("SELECT COUNT(*) FROM INFORMATION_SCHEMA")
    assert exists_params == ["CommandCenter", "Knowledge"]
    (create_sql, _), = conn.sql("CREATE TABLE")
    assert create_sql.startswith("CREATE TABLE CommandCenter.Knowledge (")
    for column in ("Source VARCHAR(200)", "Title VARCHAR(500)", "Body VARCHAR(4000)", "Embedding VECTOR(DOUBLE, 256)"):
        assert column in create_sql
    assert conn.sql("DELETE FROM CommandCenter.Knowledge") == [("DELETE FROM CommandCenter.Knowledge", None)]
    inserts = conn.sql("INSERT")
    assert len(inserts) == len(corpus)
    assert conn.commits == 1 and conn.rollbacks == 0


def test_existing_table_is_not_recreated(fake_iris) -> None:
    fake_iris["kwargs"] = {"table_exists": True}
    _store().ensure_indexed_sync()
    conn = fake_iris["connections"][0]

    assert conn.sql("CREATE TABLE") == []
    assert len(conn.sql("INSERT")) == len(build_corpus())


def test_inserts_use_bound_parameters_and_to_vector(fake_iris) -> None:
    _store().ensure_indexed_sync()
    inserts = fake_iris["connections"][0].sql("INSERT")
    doc = build_corpus()[0]

    sql, params = inserts[0]
    assert sql == (
        "INSERT INTO CommandCenter.Knowledge (Source, Title, Body, Embedding) "
        "VALUES (?, ?, ?, TO_VECTOR(?, DOUBLE, 256))"
    )
    assert params == [doc.doc_id, doc.title, doc.body, vector_literal(embed(f"{doc.title}\n{doc.body}"))]
    # No corpus text is ever interpolated into the SQL itself.
    assert all(sql == inserts[0][0] for sql, _ in inserts)


def test_reindexing_is_deterministic(fake_iris) -> None:
    _store().ensure_indexed_sync()
    _store().ensure_indexed_sync()
    first, second = fake_iris["connections"]

    assert first.sql("INSERT") == second.sql("INSERT")


def test_connects_with_configured_namespace_and_superserver_port(fake_iris) -> None:
    _store().ensure_indexed_sync()
    settings = get_settings()

    assert fake_iris["args"] == [
        (
            "iris.invalid.test",
            settings.iris_superserver_port,
            settings.iris_namespace,
            settings.iris_username,
            settings.iris_password.get_secret_value(),
        )
    ]


def test_failed_reindex_rolls_back_and_raises_unavailable(fake_iris) -> None:
    fake_iris["kwargs"] = {"fail_on": "INSERT"}
    store = _store()

    with pytest.raises(KnowledgeStoreUnavailableError):
        store.ensure_indexed_sync()
    conn = fake_iris["connections"][0]
    assert conn.rollbacks == 1 and conn.commits == 0
    assert conn.closed and store._connection is None and store._indexed is False


def test_mid_reindex_failure_rolls_back_to_the_complete_previous_rows(fake_iris) -> None:
    # First, a successful index gives the committed baseline (all 33 rows).
    _store().ensure_indexed_sync()
    baseline = fake_iris["connections"][0].committed
    assert len(baseline) == len(build_corpus())

    # Then a reindex whose 11th INSERT fails, as the live SQLCODE -104 did.
    fake_iris["kwargs"] = {"table_exists": True, "fail_insert_at": 11, "committed": baseline}
    store = _store()
    with pytest.raises(KnowledgeStoreUnavailableError):
        store.ensure_indexed_sync()
    conn = fake_iris["connections"][1]

    assert len(conn.sql("INSERT")) == 11  # DELETE + 10 inserts ran before the failure
    assert conn.committed == baseline  # ...yet nothing of that was committed
    assert conn.commits == 0 and conn.rollbacks == 1
    assert conn.autocommit_changes == [False, True]  # off for the transaction, then restored
    assert conn.closed and store._connection is None and store._indexed is False


def test_successful_reindex_commits_once_inside_a_transaction(fake_iris) -> None:
    _store().ensure_indexed_sync()
    conn = fake_iris["connections"][0]

    assert conn.autocommit_changes == [False, True]
    assert conn.autocommit is True  # search keeps the driver's default
    assert conn.commits == 1 and conn.rollbacks == 0
    assert [row[0] for row in conn.committed] == [doc.doc_id for doc in build_corpus()]


def test_unreachable_iris_raises_unavailable(fake_iris) -> None:
    fake_iris["refuse"] = True
    with pytest.raises(KnowledgeStoreUnavailableError):
        _store().ensure_indexed_sync()


def test_every_corpus_document_fits_the_table_columns() -> None:
    for doc in build_corpus():
        assert len(doc.doc_id) <= SOURCE_MAX
        assert len(doc.title) <= TITLE_MAX
        assert len(doc.body) <= BODY_MAX


def test_vector_literal_is_256_fixed_point_values() -> None:
    vector = embed("mount a database")
    literal = vector_literal(vector)
    values = literal.split(",")

    assert len(values) == 256
    assert "e" not in literal.lower()
    assert all(abs(float(v) - x) < 1e-11 for v, x in zip(values, vector))


# --- search ---


def test_search_uses_top5_vector_cosine_with_a_bound_query_vector(fake_iris) -> None:
    store = _store()
    store.ensure_indexed_sync()
    conn = fake_iris["connections"][0]
    conn.search_rows = [("operation:database.dismount", "Operation database.dismount", "Dismount...", 0.45)]
    query = "dismount database'; DROP TABLE CommandCenter.Knowledge --"

    hits = store.search_sync(query)

    (sql, params), = conn.sql("SELECT TOP")
    assert sql == (
        "SELECT TOP 5 Source, Title, Body, "
        "VECTOR_COSINE(Embedding, TO_VECTOR(?, DOUBLE, 256)) AS Score "
        "FROM CommandCenter.Knowledge ORDER BY Score DESC, Source"
    )
    assert params == [vector_literal(embed(query))]
    assert "DROP" not in sql
    assert hits == [
        KnowledgeHit(source="operation:database.dismount", title="Operation database.dismount", body="Dismount...", score=0.45)
    ]


def test_search_indexes_first_when_startup_indexing_did_not_happen(fake_iris) -> None:
    fake_iris["kwargs"] = {"table_exists": True}
    _store().search_sync("mount database")
    statements = [sql.split(" ")[0] for sql, _ in fake_iris["connections"][0].statements]

    assert statements.index("DELETE") < statements.index("INSERT")
    assert statements[-1] == "SELECT"


def test_query_without_searchable_words_returns_nothing_without_touching_iris(fake_iris) -> None:
    assert _store().search_sync("the of and ?") == []
    assert fake_iris["args"] == []


def test_search_failure_resets_so_the_next_search_reindexes(fake_iris) -> None:
    store = _store()
    store.ensure_indexed_sync()
    fake_iris["connections"][0].fail_on = "SELECT TOP"

    with pytest.raises(KnowledgeStoreUnavailableError):
        store.search_sync("mount database")
    assert store._connection is None and store._indexed is False

    store.search_sync("mount database")  # new connection: re-ensures table, reindexes, searches
    second = fake_iris["connections"][1]
    assert second.sql("INSERT") and second.sql("SELECT TOP")


def test_feature_is_disabled_by_default() -> None:
    assert Settings.model_fields["enable_knowledge_search"].default is False


# --- route ---


class _StubStore:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.queries: list[str] = []
        self.ran_on_event_loop: bool | None = None

    def search_sync(self, query: str) -> list[KnowledgeHit]:
        try:
            asyncio.get_running_loop()
            self.ran_on_event_loop = True
        except RuntimeError:
            self.ran_on_event_loop = False
        self.queries.append(query)
        if self.fail:
            raise KnowledgeStoreUnavailableError()
        return [KnowledgeHit(source="operation:database.mount", title="Operation database.mount", body="Mount.", score=0.5)]


@pytest.fixture
def route_client():
    def make(store: Any) -> TestClient:
        app.dependency_overrides[get_knowledge_store] = lambda: store
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


def test_route_returns_results_searched_off_the_event_loop(route_client) -> None:
    stub = _StubStore()
    response = route_client(stub).get("/api/iris/knowledge/search", params={"q": "mount database"})

    assert response.status_code == 200
    assert response.json() == {
        "query": "mount database",
        "results": [{"source": "operation:database.mount", "title": "Operation database.mount", "body": "Mount.", "score": 0.5}],
    }
    assert stub.queries == ["mount database"]
    assert stub.ran_on_event_loop is False


def test_route_is_503_when_disabled(route_client) -> None:
    response = route_client(None).get("/api/iris/knowledge/search", params={"q": "mount"})
    assert response.status_code == 503
    assert response.json() == {"detail": "Knowledge search is not enabled"}


def test_route_is_disabled_without_configuration() -> None:
    # No override and no lifespan-created store: the real dependency says disabled.
    response = TestClient(app).get("/api/iris/knowledge/search", params={"q": "mount"})
    assert response.status_code == 503


def test_route_failure_is_a_safe_502(route_client) -> None:
    response = route_client(_StubStore(fail=True)).get("/api/iris/knowledge/search", params={"q": "mount"})

    assert response.status_code == 502
    assert response.json() == {"detail": "Could not search the knowledge base in IRIS"}
    assert "test-password-not-real" not in response.text


@pytest.mark.parametrize("params", [{}, {"q": ""}, {"q": "x" * 501}])
def test_route_validates_the_query(route_client, params) -> None:
    assert route_client(_StubStore()).get("/api/iris/knowledge/search", params=params).status_code == 422


def test_route_is_get_only(route_client) -> None:
    assert route_client(_StubStore()).post("/api/iris/knowledge/search?q=mount").status_code == 405


# --- startup ---


class _FakeStore:
    instances: list["_FakeStore"] = []
    fail = False

    def __init__(self, settings: Any):
        self.indexed = 0
        self.closed = False
        _FakeStore.instances.append(self)

    def ensure_indexed_sync(self) -> int:
        if _FakeStore.fail:
            raise KnowledgeStoreUnavailableError()
        self.indexed += 1
        return 1

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def lifespan_env(monkeypatch: pytest.MonkeyPatch):
    import app.main as main_module

    _FakeStore.instances = []
    _FakeStore.fail = False
    monkeypatch.setattr(main_module, "IRISKnowledgeStore", _FakeStore)
    get_settings.cache_clear()
    yield main_module, monkeypatch
    get_settings.cache_clear()
    app.state.knowledge_store = None


@pytest.mark.asyncio
async def test_startup_indexes_when_enabled_and_closes_at_shutdown(lifespan_env) -> None:
    main_module, monkeypatch = lifespan_env
    monkeypatch.setenv("ENABLE_KNOWLEDGE_SEARCH", "true")

    async with main_module.lifespan(main_module.app):
        (store,) = _FakeStore.instances
        assert store.indexed == 1
        assert main_module.app.state.knowledge_store is store

    assert store.closed


@pytest.mark.asyncio
async def test_startup_survives_unreachable_iris(lifespan_env) -> None:
    main_module, monkeypatch = lifespan_env
    monkeypatch.setenv("ENABLE_KNOWLEDGE_SEARCH", "true")
    _FakeStore.fail = True

    async with main_module.lifespan(main_module.app):
        assert main_module.app.state.knowledge_store is _FakeStore.instances[0]


@pytest.mark.asyncio
async def test_startup_does_nothing_when_disabled(lifespan_env) -> None:
    main_module, monkeypatch = lifespan_env
    monkeypatch.setenv("ENABLE_KNOWLEDGE_SEARCH", "false")

    async with main_module.lifespan(main_module.app):
        assert main_module.app.state.knowledge_store is None

    assert _FakeStore.instances == []
