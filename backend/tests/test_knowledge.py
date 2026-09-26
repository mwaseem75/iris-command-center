"""Tests for the knowledge corpus (app/knowledge/corpus.py) and the
deterministic hashed bag-of-words embedder (app/knowledge/embedding.py).
Pure Python — no IRIS, no network."""

import math
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.authorization.operations import OPERATION_REGISTRY
from app.capabilities import CAPABILITY_REGISTRY
from app.knowledge.corpus import build_corpus
from app.knowledge.embedding import DIMENSIONS, embed, tokenize

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


# --- embedder ---


def test_embedding_has_256_dimensions() -> None:
    assert DIMENSIONS == 256
    assert len(embed("Dismount a database")) == 256
    assert len(embed("")) == 256


def test_embedding_is_l2_normalized() -> None:
    for text in ("journal purge archived", "iris", "Run task now " * 50):
        assert math.isclose(math.sqrt(sum(v * v for v in embed(text))), 1.0, rel_tol=1e-9)


def test_text_without_tokens_embeds_to_zero_vector() -> None:
    assert embed("") == [0.0] * DIMENSIONS
    assert embed("the of and ?!") == [0.0] * DIMENSIONS


def test_embedding_is_deterministic_within_a_process() -> None:
    assert embed("Enable a web application") == embed("Enable a web application")


def test_embedding_is_deterministic_across_processes_and_hash_seeds() -> None:
    # Python's built-in hash() is randomized per process; the embedder
    # must not depend on it.
    script = "from app.knowledge.embedding import embed; print(repr(embed('Mount database USER')))"
    outputs = set()
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        run = subprocess.run(
            [sys.executable, "-c", script], cwd=BACKEND_DIR, env=env, capture_output=True, text=True, check=True
        )
        outputs.add(run.stdout)
    assert outputs == {repr(embed("Mount database USER")) + "\n"}


def test_tokenize_lowercases_splits_punctuation_and_drops_stopwords() -> None:
    assert tokenize("What is journal.update_purge_archived?") == ["journal", "update", "purge", "archived"]
    assert tokenize("%Admin_Manage:U") == ["admin", "manage", "u"]


def test_bigrams_make_word_order_matter() -> None:
    assert embed("database mount") != embed("mount database")


def test_related_text_scores_higher_than_unrelated_text() -> None:
    query = embed("dismount database")
    assert _cosine(query, embed("Dismount a mounted database")) > _cosine(query, embed("Run a scheduled task now"))


# --- corpus ---


def test_corpus_has_one_document_per_operation_and_capability() -> None:
    corpus = build_corpus()
    ids = [doc.doc_id for doc in corpus]

    assert len(corpus) == len(OPERATION_REGISTRY) + len(CAPABILITY_REGISTRY)
    assert len(set(ids)) == len(ids)
    assert {f"operation:{name}" for name in OPERATION_REGISTRY} <= set(ids)
    assert sum(doc.source == "capability" for doc in corpus) == len(CAPABILITY_REGISTRY)
    assert all(doc.title and doc.body for doc in corpus)


def test_operation_document_restates_registry_fields() -> None:
    operation = OPERATION_REGISTRY["journal.update_purge_archived"]
    doc = next(d for d in build_corpus() if d.doc_id == "operation:journal.update_purge_archived")

    assert operation.description in doc.body
    assert "Kind: Mutating." in doc.body
    assert "Confirmation: required." in doc.body
    for privilege in operation.required_privileges:
        assert f"%Admin_{privilege.value}" in doc.body


def test_capability_document_restates_registry_fields() -> None:
    entry = next(e for e in CAPABILITY_REGISTRY if e.command_center_path)
    doc = next(d for d in build_corpus() if d.doc_id == f"capability:{entry.method} {entry.endpoint}")

    assert doc.title == entry.capability
    assert f"{entry.method} {entry.endpoint}" in doc.body
    assert entry.command_center_path in doc.body
    assert entry.notes in doc.body


def test_corpus_is_deterministic() -> None:
    assert build_corpus() == build_corpus()


def test_corpus_contains_no_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    # Words like "JWT" or "password" legitimately appear in capability
    # descriptions; what must never appear is a secret VALUE.
    text = "\n".join(f"{doc.title}\n{doc.body}" for doc in build_corpus())

    assert os.environ["IRIS_PASSWORD"] not in text  # conftest's configured password
    assert re.search(r"eyJ[A-Za-z0-9_-]{10,}", text) is None  # JWT-shaped token
    assert re.search(r"(?i)bearer\s+[A-Za-z0-9._~+/-]{16,}", text) is None
    assert re.search(r"(?i)authorization\s*:", text) is None  # an Authorization header
    assert re.search(r"(?i)(password|secret|api[_-]?key)\s*[=:]\s*\S", text) is None
