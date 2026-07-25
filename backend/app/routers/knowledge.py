from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import KnowledgeChunk, KnowledgeDocument, User
from app.schemas import KnowledgeSearchRequest, KnowledgeSearchResponse, KnowledgeStatsResponse
from app.services.auth_service import get_current_user
from app.services.knowledge_base import retrieve_knowledge

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/stats", response_model=KnowledgeStatsResponse)
async def stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    document_count = await db.scalar(select(func.count()).select_from(KnowledgeDocument))
    chunk_count = await db.scalar(select(func.count()).select_from(KnowledgeChunk))
    categories_result = await db.execute(select(KnowledgeDocument.category).distinct())
    categories = [row[0] for row in categories_result.all()]
    return KnowledgeStatsResponse(
        document_count=document_count or 0,
        chunk_count=chunk_count or 0,
        categories=categories,
    )


@router.post("/search", response_model=KnowledgeSearchResponse)
async def search(
    req: KnowledgeSearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    snippets = await retrieve_knowledge(
        db,
        req.query,
        categories=req.categories,
        limit=req.limit,
    )
    return KnowledgeSearchResponse(results=[snippet.to_dict() for snippet in snippets])
