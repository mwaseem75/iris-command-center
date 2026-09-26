"""A single, read-only route: vector search over the Command Center's
knowledge corpus, stored in and searched by IRIS (see
app/knowledge/store.py). No LLM is involved — results are the stored
corpus documents themselves, ranked by VECTOR_COSINE.

Returns 503 while the feature is disabled (Settings.enable_knowledge_search
is off by default). No mutating call exists anywhere in this module; the
store's only writes happen at startup, to its own table.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_knowledge_store
from app.knowledge.store import (
    IRISKnowledgeStore,
    KnowledgeSearchResponse,
    KnowledgeStoreUnavailableError,
)

router = APIRouter(prefix="/api/iris", tags=["knowledge"])


@router.get("/knowledge/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    q: str = Query(..., min_length=1, max_length=500),
    store: IRISKnowledgeStore | None = Depends(get_knowledge_store),
) -> KnowledgeSearchResponse:
    if store is None:
        raise HTTPException(status_code=503, detail="Knowledge search is not enabled")
    # DB-API over the Native API driver is blocking — keep it off the event loop.
    try:
        results = await asyncio.get_running_loop().run_in_executor(None, store.search_sync, q)
    except KnowledgeStoreUnavailableError:
        raise HTTPException(status_code=502, detail="Could not search the knowledge base in IRIS") from None
    return KnowledgeSearchResponse(query=q, results=results)
