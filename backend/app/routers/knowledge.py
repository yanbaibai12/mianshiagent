from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import KnowledgeChunk, KnowledgeDocument, User
from app.schemas import KnowledgeSearchRequest, KnowledgeSearchResponse, KnowledgeStatsResponse
from app.services.audit import log_audit_event
from app.services.auth_service import get_current_user, require_admin_user
from app.services.interview_question_bank import DEFAULT_INTERVIEW_BANK, import_interview_question_bank
from app.services.knowledge_base import retrieve_knowledge
from app.services.vector_store import sync_knowledge_to_vector_store, vector_store_status

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class InterviewBankImportRequest(BaseModel):
    path: str | None = None
    skip_vector: bool = False
    recreate_vector: bool = False


def _resolve_bank_path(path: str | None) -> Path:
    if not path:
        return DEFAULT_INTERVIEW_BANK
    knowledge_root = DEFAULT_INTERVIEW_BANK.parent.resolve()
    resolved = (knowledge_root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if knowledge_root not in resolved.parents and resolved != knowledge_root:
        raise HTTPException(status_code=400, detail="题库文件必须位于 backend/knowledge 目录下")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="题库文件不存在")
    return resolved


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
        vector_store=await vector_store_status(db),
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


@router.post("/sync")
async def sync_vector_index(
    recreate: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return await sync_knowledge_to_vector_store(db, recreate=recreate)


@router.post("/admin/import-interview-bank")
async def admin_import_interview_bank(
    req: InterviewBankImportRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_user),
) -> dict[str, Any]:
    path = _resolve_bank_path(req.path)
    try:
        result = await import_interview_question_bank(
            db,
            path=path,
            skip_vector=req.skip_vector,
            recreate_vector=req.recreate_vector,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_audit_event(
        db,
        event_type="knowledge.import_interview_bank",
        resource_type="knowledge_bank",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        organization_id=None,
        resource_id=path.name,
        request=request,
        metadata={
            "documents": result.get("documents"),
            "questions": result.get("questions"),
            "chunks": result.get("chunks"),
            "duplicates_removed": result.get("duplicates_removed"),
            "vector_status": (result.get("vector_sync") or {}).get("status") if isinstance(result.get("vector_sync"), dict) else None,
        },
    )
    await db.commit()
    return result
