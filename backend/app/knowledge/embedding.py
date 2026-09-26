"""A deterministic, dependency-free text embedder for the knowledge search:
hashed bag-of-words plus word bigrams ("feature hashing"), projected into
a fixed 256-dimensional vector and L2-normalized.

This is NOT a learned/semantic model and no LLM is involved — similarity
means shared (normalized) words and word pairs. It is used for BOTH
documents and queries, so their vectors are always comparable.

Determinism: features are hashed with BLAKE2b (never Python's built-in,
per-process-randomized hash()), so the same text yields the same vector
in every process, on every machine.
"""

import hashlib
import math
import re

DIMENSIONS = 256

_BIGRAM_WEIGHT = 0.5
_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Small, fixed English stopword list — function words that would otherwise
# dominate every vector without distinguishing any document.
_STOPWORDS = frozenset(
    "a an and are as at be by for from has have how i in is it its of on or "
    "that the this to was what when which who why will with do does can my".split()
)


def tokenize(text: str) -> list[str]:
    """Lowercased alphanumeric runs, minus stopwords. Punctuation splits
    tokens, so "journal.update_purge_archived" -> journal, update, purge,
    archived and "%Admin_Manage:U" -> admin, manage, u."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


def _bucket(feature: str) -> tuple[int, float]:
    """Stable (index, sign) for one feature. The sign bit halves the bias
    hash collisions would otherwise add to cosine similarity."""
    digest = int.from_bytes(hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest(), "big")
    return digest % DIMENSIONS, (1.0 if digest >> 63 else -1.0)


def embed(text: str) -> list[float]:
    """256 floats with L2 norm 1.0 — or all zeros when `text` has no
    tokens, since an empty vector cannot be normalized (callers must not
    search with it)."""
    tokens = tokenize(text)
    vector = [0.0] * DIMENSIONS
    features = [(token, 1.0) for token in tokens] + [
        (f"{a} {b}", _BIGRAM_WEIGHT) for a, b in zip(tokens, tokens[1:])
    ]
    for feature, weight in features:
        index, sign = _bucket(feature)
        vector[index] += sign * weight

    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        return vector
    return [v / norm for v in vector]
