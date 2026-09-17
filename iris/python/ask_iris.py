"""Ask IRIS — the Vector Search + LLM/LangChain bonus feature.

A retrieval-augmented question-answering assistant grounded in this project's
own documentation (README.md, docs/api-matrix.md, docs/health-analyzer.md —
whatever .md files a deployment copies into DOCS_DIR). It never answers from
the model's general knowledge alone: every answer is generated only from
chunks retrieved by IRIS's native SQL Vector Search (VECTOR_COSINE over a
VECTOR column, confirmed live on 2026.2 Community Edition — see
docs/api-matrix.md section 13), and every response carries the sources it
was grounded in so an answer can be checked against the real doc.

Design mirrors health_analyzer.py: the parts that don't need IRIS or a
network call (`chunk_markdown`) are pure functions, independently unit
tested (tests/test_ask_iris.py). Everything that does need IRIS
(`iris.sql.exec`, `iris.cls('%Wallet.Secret')`) or OpenAI is isolated in
the functions below it, and only exercised through
iris/classes/ISOE/AskIris.cls.

Where the OpenAI key lives: this project already has a feature purpose-built
for holding a secret server-side and never returning its value over REST —
Wallets (Phase 6). The key is stored as a wallet secret named by
WALLET_SECRET_NAME and read here via the documented, non-REST
`%Wallet.Secret.GetSecretValue()` ClassMethod (confirmed live — see
docs/ask-iris.md). It is never logged, never included in an error message
verbatim, and never crosses back over HTTP to the browser.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any


class AskIrisNotConfiguredError(Exception):
    """Raised for every "not set up yet" condition (no wallet secret, no docs
    corpus, no index built yet) — distinguished from other exceptions so
    ISOE.AskIris.cls can report a calm 'not configured' status instead of a
    scary error, and the frontend can render it as guidance, not a failure."""


WALLET_SECRET_NAME = "AskIris.OpenAIApiKey"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
CHAT_MODEL = "gpt-4o-mini"
DEFAULT_TOP_K = 5
INDEX_TABLE = "ISOE.AskIrisChunk"

# Docs corpus directory. A deployment copies README.md, docs/api-matrix.md,
# and docs/health-analyzer.md here (see docs/ask-iris.md) — kept alongside
# this module rather than reading the live project checkout, matching how
# health_analyzer.py itself is deployed as a standalone copy, not a mount.
DOCS_DIR = os.environ.get("ASKIRIS_DOCS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "docs-corpus"
)

MAX_CHUNK_CHARS = 1500
CHUNK_OVERLAP_CHARS = 200


# ---------------------------------------------------------------------------
# Pure functions — no I/O, no IRIS, no OpenAI. See tests/test_ask_iris.py.
# ---------------------------------------------------------------------------

def _split_by_headings(text: str) -> list[tuple[str, str]]:
    """Splits markdown text into (heading, body) sections at ATX headers (#-####)."""
    heading_re = re.compile(r"^#{1,4}\s+\S")
    sections: list[tuple[str, str]] = []
    current_heading = "(document start)"
    current_lines: list[str] = []
    for line in text.splitlines():
        if heading_re.match(line):
            if current_lines:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = line.lstrip("#").strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_heading, "\n".join(current_lines).strip()))
    return [(heading, body) for heading, body in sections if body]


def _split_long_text(text: str, max_chars: int = MAX_CHUNK_CHARS, overlap: int = CHUNK_OVERLAP_CHARS) -> list[str]:
    """Splits text into <= max_chars pieces with a small overlap so a chunk
    boundary doesn't sever the sentence a retrieval hit actually needs."""
    if len(text) <= max_chars:
        return [text]
    pieces = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        pieces.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return pieces


def chunk_markdown(text: str, source: str) -> list[dict[str, str]]:
    """Splits one markdown document into retrieval-sized chunks.

    :param text: raw markdown content.
    :param source: a short label identifying the document (e.g. "README.md"),
        carried through to search results and shown as a citation.
    :returns: [{"source": str, "heading": str, "text": str}, ...]
    """
    chunks = []
    for heading, body in _split_by_headings(text):
        for piece in _split_long_text(body):
            piece = piece.strip()
            if piece:
                chunks.append({"source": source, "heading": heading, "text": piece})
    return chunks


# ---------------------------------------------------------------------------
# IRIS / OpenAI-touching functions.
# ---------------------------------------------------------------------------

def get_openai_api_key() -> str:
    """Reads the OpenAI API key from this project's own Wallets feature.
    Raises AskIrisNotConfiguredError (never the raw wallet exception, which
    may include the secret name but never the value) if it hasn't been set up."""
    import iris

    try:
        raw = iris.cls("%Wallet.Secret").GetSecretValue(WALLET_SECRET_NAME)
    except Exception as exc:
        raise AskIrisNotConfiguredError(
            f"No OpenAI API key configured. Create a wallet secret named "
            f"'{WALLET_SECRET_NAME}' on the Wallets page — see docs/ask-iris.md."
        ) from exc

    try:
        data = json.loads(raw) if raw else {}
        key = data.get("apiKey")
    except (ValueError, TypeError, AttributeError):
        key = None

    if not key:
        raise AskIrisNotConfiguredError(
            f"Wallet secret '{WALLET_SECRET_NAME}' exists but has no 'apiKey' field. "
            "See docs/ask-iris.md for the expected shape."
        )
    return key


def _read_docs_corpus() -> list[tuple[str, str]]:
    if not os.path.isdir(DOCS_DIR):
        raise AskIrisNotConfiguredError(
            f"Docs corpus directory not found at {DOCS_DIR}. See docs/ask-iris.md "
            "for the deployment step that populates it."
        )
    sources = []
    for name in sorted(os.listdir(DOCS_DIR)):
        if name.endswith(".md"):
            with open(os.path.join(DOCS_DIR, name), "r", encoding="utf-8") as f:
                sources.append((name, f.read()))
    if not sources:
        raise AskIrisNotConfiguredError(
            f"No .md files found in {DOCS_DIR}. See docs/ask-iris.md for the "
            "deployment step that populates it."
        )
    return sources


def ensure_index_table() -> None:
    import iris

    iris.sql.exec(
        f"CREATE TABLE IF NOT EXISTS {INDEX_TABLE} ("
        f"Source VARCHAR(120), Heading VARCHAR(300), ChunkText VARCHAR(4000), "
        f"Embedding VECTOR(DOUBLE, {EMBEDDING_DIMENSIONS}))"
    )


def _embed_documents(texts: list[str], api_key: str) -> list[list[float]]:
    from langchain_openai import OpenAIEmbeddings

    embedder = OpenAIEmbeddings(model=EMBEDDING_MODEL, api_key=api_key)
    return embedder.embed_documents(texts)


def _embed_query(text: str, api_key: str) -> list[float]:
    from langchain_openai import OpenAIEmbeddings

    embedder = OpenAIEmbeddings(model=EMBEDDING_MODEL, api_key=api_key)
    return embedder.embed_query(text)


def reindex() -> dict[str, Any]:
    """Rebuilds the vector index from scratch from the docs corpus. Makes one
    batched OpenAI embeddings call for all chunks, not one call per chunk."""
    import iris

    api_key = get_openai_api_key()
    sources = _read_docs_corpus()

    chunks: list[dict[str, str]] = []
    for name, text in sources:
        chunks.extend(chunk_markdown(text, name))
    if not chunks:
        raise AskIrisNotConfiguredError("Docs corpus produced no chunks to index.")

    vectors = _embed_documents([c["text"] for c in chunks], api_key)

    ensure_index_table()
    iris.sql.exec(f"DELETE FROM {INDEX_TABLE}")
    for chunk, vector in zip(chunks, vectors):
        vec_str = ",".join(str(v) for v in vector)
        iris.sql.exec(
            f"INSERT INTO {INDEX_TABLE} (Source, Heading, ChunkText, Embedding) "
            f"VALUES (?, ?, ?, TO_VECTOR(?, DOUBLE))",
            chunk["source"],
            chunk["heading"][:300],
            chunk["text"][:4000],
            vec_str,
        )
    return {"chunksIndexed": len(chunks), "sources": sorted({c["source"] for c in chunks})}


def search(question: str, top_k: int = DEFAULT_TOP_K, api_key: str | None = None) -> list[dict[str, Any]]:
    """Embeds `question` and returns the top_k most similar indexed chunks,
    ranked by cosine similarity (IRIS's native VECTOR_COSINE, not an
    approximation computed in Python)."""
    import iris

    api_key = api_key or get_openai_api_key()
    query_vector = _embed_query(question, api_key)
    vec_str = ",".join(str(v) for v in query_vector)

    try:
        rs = iris.sql.exec(
            f"SELECT TOP ? Source, Heading, ChunkText, "
            f"VECTOR_COSINE(Embedding, TO_VECTOR(?, DOUBLE)) AS Score "
            f"FROM {INDEX_TABLE} ORDER BY Score DESC",
            top_k,
            vec_str,
        )
    except Exception as exc:
        raise AskIrisNotConfiguredError(
            "The Ask IRIS index hasn't been built yet. Use the Rebuild index action first."
        ) from exc

    results = [
        {"source": row[0], "heading": row[1], "text": row[2], "score": round(float(row[3]), 4)}
        for row in rs
    ]
    if not results:
        raise AskIrisNotConfiguredError(
            "The Ask IRIS index is empty. Use the Rebuild index action first."
        )
    return results


def ask(question: str, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
    """Retrieval-augmented answer: retrieves grounding chunks via IRIS Vector
    Search, then asks the chat model to answer using only that context."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    api_key = get_openai_api_key()
    chunks = search(question, top_k=top_k, api_key=api_key)

    context = "\n\n".join(
        f"[{i + 1}] (from {c['source']} — {c['heading']}):\n{c['text']}"
        for i, c in enumerate(chunks)
    )
    system = SystemMessage(
        content=(
            "You are Ask IRIS, an assistant embedded in the IRIS Command Center "
            "management portal. Answer the user's question using ONLY the numbered "
            "context below, drawn from this project's own documentation. Cite the "
            "sources you used by their bracketed number. If the context doesn't "
            "contain the answer, say you don't know rather than guessing — never "
            "invent IRIS behavior that isn't in the provided context.\n\n"
            f"Context:\n{context}"
        )
    )
    llm = ChatOpenAI(model=CHAT_MODEL, api_key=api_key, temperature=0)
    response = llm.invoke([system, HumanMessage(content=question)])

    return {
        "answer": response.content,
        "sources": [{"source": c["source"], "heading": c["heading"], "score": c["score"]} for c in chunks],
    }


def status() -> dict[str, Any]:
    """Cheap, side-effect-free check the frontend can call before offering the
    chat UI: is a key configured, and has an index been built."""
    import iris

    try:
        get_openai_api_key()
        configured = True
        detail = None
    except AskIrisNotConfiguredError as exc:
        configured = False
        detail = str(exc)

    try:
        rs = iris.sql.exec(f"SELECT COUNT(*) FROM {INDEX_TABLE}")
        indexed_chunks = list(rs)[0][0]
    except Exception:
        indexed_chunks = 0

    return {"configured": configured, "detail": detail, "indexedChunks": indexed_chunks}
