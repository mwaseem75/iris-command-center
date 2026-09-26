"""Knowledge search endpoint (IRIS vector search, no LLM).

Returns the stored documents ranked by VECTOR_COSINE, or 503 when the
feature is turned off.
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
    # The driver is blocking, so run the search in a thread.
    try:
        results = await asyncio.get_running_loop().run_in_executor(None, store.search_sync, q)
    except KnowledgeStoreUnavailableError:
        raise HTTPException(status_code=502, detail="Could not search the knowledge base in IRIS") from None
    return KnowledgeSearchResponse(query=q, results=results)
