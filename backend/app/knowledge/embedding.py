"""Simple text embedding for knowledge search (hashed bag-of-words).

Words and word pairs are hashed into 256 buckets and the vector is
normalized. It matches shared words, not meaning, and needs no model or
extra packages. We use BLAKE2b instead of hash() so the result is the same
in every process.
"""

import hashlib
import math
import re

DIMENSIONS = 256

_BIGRAM_WEIGHT = 0.5
_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Common words that would otherwise dominate every vector.
_STOPWORDS = frozenset(
    "a an and are as at be by for from has have how i in is it its of on or "
    "that the this to was what when which who why will with do does can my".split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase words without stopwords. Punctuation splits words, so
    "journal.update_purge_archived" -> journal, update, purge, archived.
    """
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


def _bucket(feature: str) -> tuple[int, float]:
    """Bucket index and sign for a feature (the sign reduces collision bias)."""
    digest = int.from_bytes(hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest(), "big")
    return digest % DIMENSIONS, (1.0 if digest >> 63 else -1.0)


def embed(text: str) -> list[float]:
    """Return a normalized 256-float vector (all zeros if there are no words)."""
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
