import hashlib
import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Resume, ResumeChunk
from app.services.rerank_service import rerank_documents, rerank_enabled
from app.services.vector_store import delete_vector_payloads, search_vector_payloads, upsert_vector_payloads
from app.utils.time import utc_now


HARD_SKILL_TERMS = [
    "Python",
    "Java",
    "JavaScript",
    "TypeScript",
    "React",
    "Vue",
    "Node.js",
    "FastAPI",
    "Django",
    "Flask",
    "Spring",
    "SQL",
    "MySQL",
    "PostgreSQL",
    "Redis",
    "MongoDB",
    "Docker",
    "Kubernetes",
    "Linux",
    "Git",
    "CI/CD",
    "Agent",
    "RAG",
    "BM25",
    "RRF",
    "Qdrant",
    "BGE-M3",
    "Embedding",
    "Function Calling",
    "Tool Calling",
    "Prompt Injection",
    "API",
    "任务队列",
    "异步",
    "缓存",
    "日志",
    "监控",
    "索引",
    "检索",
    "重排",
    "优化",
    "接口",
    "联调",
    "排查",
]

SECTION_LABELS = {
    "personal": "基本信息",
    "education": "教育经历",
    "skills": "技术栈",
    "experience": "实习/工作经历",
    "project": "项目经历",
    "summary": "自我评价",
    "full_text": "原始简历",
}


@dataclass
class ResumeSnippet:
    chunk_id: str
    resume_id: str
    section: str
    item_title: str
    chunk_index: int
    content: str
    keywords: list[str]
    score: float
    retrieval_source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "resume_id": self.resume_id,
            "resume_version_id": "",
            "section": self.section,
            "section_type": self.section,
            "section_label": SECTION_LABELS.get(self.section, self.section),
            "item_title": self.item_title,
            "section_title": self.item_title,
            "project_name": self.item_title if self.section == "project" else "",
            "experience_name": self.item_title if self.section == "experience" else "",
            "chunk_index": self.chunk_index,
            "content": self.content,
            "source_text": self.content,
            "keywords": self.keywords[:12],
            "score": round(self.score, 3),
            "retrieval_source": self.retrieval_source,
        }


def _settings():
    return get_settings()


def normalize_terms(text: str) -> list[str]:
    text = (text or "").lower()
    terms = re.findall(r"[a-zA-Z][a-zA-Z0-9+#./-]{1,}|[\u4e00-\u9fa5]{2,8}", text)
    stop_words = {
        "岗位职责",
        "任职要求",
        "岗位要求",
        "工作经验",
        "相关经验",
        "优先考虑",
        "以上学历",
        "负责",
        "参与",
        "以及",
        "通过",
        "进行",
        "相关",
        "能力",
        "要求",
        "熟悉",
        "掌握",
        "具备",
    }
    result: list[str] = []
    seen: set[str] = set()
    detected_hard_terms: list[str] = []
    for term in HARD_SKILL_TERMS:
        normalized_term = term.lower()
        if re.search(r"[a-zA-Z0-9]", normalized_term):
            pattern = rf"(?<![a-zA-Z0-9+#./-]){re.escape(normalized_term)}(?![a-zA-Z0-9+#./-])"
            if re.search(pattern, text, re.IGNORECASE):
                detected_hard_terms.append(normalized_term)
        elif normalized_term in text:
            detected_hard_terms.append(normalized_term)

    for term in [*terms, *detected_hard_terms]:
        normalized = term.strip().lower()
        if len(normalized) < 2 or normalized in stop_words or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result[:100]


def _token_estimate(content: str) -> int:
    return max(1, len(content) // 2)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(_as_text(item) for item in value if _as_text(item))
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            text = _as_text(item)
            if text:
                lines.append(f"{key}: {text}")
        return "\n".join(lines)
    return str(value).strip()


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item).strip(" ，,、;；。")
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def extract_keywords(text: str) -> list[str]:
    found = [term for term in HARD_SKILL_TERMS if re.search(re.escape(term), text, re.IGNORECASE)]
    found.extend(re.findall(r"[a-zA-Z][a-zA-Z0-9+#./-]{1,}|[\u4e00-\u9fa5]{2,8}", text))
    return _dedupe(found)[:40]


def _recursive_split_segment(text: str, max_chars: int, separators: list[str]) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    if not separators:
        return [text[index : index + max_chars].strip() for index in range(0, len(text), max_chars) if text[index : index + max_chars].strip()]

    separator = separators[0]
    parts = text.split(separator)
    if len(parts) == 1:
        return _recursive_split_segment(text, max_chars, separators[1:])

    chunks: list[str] = []
    current = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        candidate = f"{current}{separator}{part}".strip() if current else part
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.extend(_recursive_split_segment(current, max_chars, separators[1:]))
        current = part
    if current:
        chunks.extend(_recursive_split_segment(current, max_chars, separators[1:]))
    return chunks


def recursive_chunk_text(text: str, *, chunk_size: int | None = None, overlap: int | None = None) -> list[str]:
    settings = _settings()
    max_chars = max(200, chunk_size or settings.RESUME_CHUNK_SIZE)
    overlap_chars = max(0, min(overlap if overlap is not None else settings.RESUME_CHUNK_OVERLAP, max_chars // 3))
    base_chunks = _recursive_split_segment(
        re.sub(r"\n{3,}", "\n\n", text or ""),
        max_chars,
        ["\n\n", "\n", "。", "；", ";", "，", ",", " "],
    )
    if not base_chunks or overlap_chars <= 0:
        return base_chunks

    chunks = [base_chunks[0]]
    for previous, current in zip(base_chunks, base_chunks[1:], strict=False):
        prefix = previous[-overlap_chars:].strip()
        merged = f"{prefix}\n{current}".strip() if prefix else current
        chunks.append(merged[: max_chars + overlap_chars])
    return chunks


def _item_title(item: dict[str, Any], keys: tuple[str, ...], fallback: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    return fallback


def _structured_sources(resume: Resume) -> list[tuple[str, str, str]]:
    data = resume.parsed_data if isinstance(resume.parsed_data, dict) else {}
    sources: list[tuple[str, str, str]] = []

    skills = data.get("skills") if isinstance(data, dict) else []
    if skills:
        sources.append(("skills", "技术栈", f"技术栈：{_as_text(skills)}"))

    for index, item in enumerate(data.get("education") or [], 1):
        if isinstance(item, dict):
            title = _item_title(item, ("school", "学校", "name"), f"教育经历 {index}")
            sources.append(("education", title, f"教育经历：{_as_text(item)}"))

    for index, item in enumerate(data.get("experience") or [], 1):
        if isinstance(item, dict):
            title = _item_title(item, ("company", "公司", "role", "职位"), f"实习/工作经历 {index}")
            sources.append(("experience", title, f"实习/工作经历：{_as_text(item)}"))

    for index, item in enumerate(data.get("projects") or [], 1):
        if isinstance(item, dict):
            title = _item_title(item, ("name", "project_name", "项目名", "title"), f"项目经历 {index}")
            sources.append(("project", title, f"项目经历：{_as_text(item)}"))

    summary = _as_text(data.get("summary"))
    if summary:
        sources.append(("summary", "自我评价", f"自我评价：{summary}"))

    if not sources and resume.original_text:
        sources.append(("full_text", resume.title, resume.original_text))

    return sources


def build_resume_chunk_payloads(resume: Resume) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for section, item_title, source_text in _structured_sources(resume):
        for index, chunk_text in enumerate(recursive_chunk_text(source_text), 1):
            content = chunk_text.strip()
            if len(content) < 8:
                continue
            payloads.append(
                {
                    "section": section,
                    "item_title": item_title,
                    "chunk_index": index,
                    "content": content,
                    "keywords": extract_keywords(f"{item_title}\n{content}"),
                    "token_estimate": _token_estimate(content),
                    "source_hash": hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest(),
                }
            )
    return payloads


def _resume_collection_name() -> str:
    return _settings().QDRANT_RESUME_COLLECTION


def _vector_payload(chunk: ResumeChunk) -> dict[str, Any]:
    return {
        "doc_type": "resume",
        "chunk_id": str(chunk.id),
        "resume_id": str(chunk.resume_id),
        "resume_version_id": "",
        "user_id": str(chunk.user_id),
        "organization_id": str(chunk.organization_id) if chunk.organization_id else "",
        "section": chunk.section,
        "section_type": chunk.section,
        "item_title": chunk.item_title,
        "section_title": chunk.item_title,
        "project_name": chunk.item_title if chunk.section == "project" else "",
        "experience_name": chunk.item_title if chunk.section == "experience" else "",
        "chunk_index": chunk.chunk_index,
        "keywords": chunk.keywords or [],
        "content": chunk.content,
        "source_text": chunk.content,
        "created_at": chunk.created_at.isoformat() if chunk.created_at else "",
    }


async def delete_resume_vectors(user_id: Any, resume_id: Any) -> dict[str, Any]:
    return await delete_vector_payloads(
        _resume_collection_name(),
        filters={"doc_type": "resume", "user_id": str(user_id), "resume_id": str(resume_id)},
    )


async def reindex_resume_chunks(db: AsyncSession, resume: Resume) -> dict[str, Any]:
    await delete_resume_vectors(resume.user_id, resume.id)
    await db.execute(delete(ResumeChunk).where(ResumeChunk.resume_id == resume.id))

    chunk_payloads = build_resume_chunk_payloads(resume)
    chunks: list[ResumeChunk] = []
    for payload in chunk_payloads:
        chunk = ResumeChunk(
            resume_id=resume.id,
            user_id=resume.user_id,
            organization_id=resume.organization_id,
            section=payload["section"],
            item_title=payload["item_title"],
            chunk_index=payload["chunk_index"],
            content=payload["content"],
            keywords=payload["keywords"],
            token_estimate=payload["token_estimate"],
            source_hash=payload["source_hash"],
            embedding_status="pending",
        )
        db.add(chunk)
        chunks.append(chunk)
    await db.flush()

    vector_items = [
        (str(chunk.id), f"{SECTION_LABELS.get(chunk.section, chunk.section)}\n{chunk.item_title}\n{chunk.content}", _vector_payload(chunk))
        for chunk in chunks
    ]
    vector_result = await upsert_vector_payloads(_resume_collection_name(), vector_items)
    indexed = vector_result.get("status") == "success"
    for chunk in chunks:
        chunk.embedding_status = "indexed" if indexed else "failed" if vector_result.get("status") == "failed" else "skipped"
        chunk.vector_point_id = str(chunk.id) if indexed else None
        chunk.updated_at = utc_now()

    return {
        "status": "success" if chunks else "empty",
        "chunk_count": len(chunks),
        "vector": vector_result,
        "collection": _resume_collection_name(),
    }


async def ensure_resume_chunks(db: AsyncSession, resume: Resume) -> dict[str, Any]:
    count = len((await db.execute(select(ResumeChunk.id).where(ResumeChunk.resume_id == resume.id))).all())
    if count > 0:
        return {"status": "already_indexed", "chunk_count": count, "collection": _resume_collection_name()}
    return await reindex_resume_chunks(db, resume)


async def reindex_all_resume_chunks(
    db: AsyncSession,
    *,
    user_id: Any | None = None,
    only_missing: bool = True,
    limit: int | None = None,
) -> dict[str, Any]:
    stmt = select(Resume).order_by(Resume.updated_at.desc())
    if user_id is not None:
        stmt = stmt.where(Resume.user_id == user_id)
    if limit is not None:
        stmt = stmt.limit(max(1, int(limit)))

    resumes = (await db.execute(stmt)).scalars().all()
    summary: dict[str, Any] = {
        "status": "success",
        "resume_count": len(resumes),
        "processed_count": 0,
        "skipped_count": 0,
        "chunk_count": 0,
        "indexed_count": 0,
        "failed_count": 0,
        "collection": _resume_collection_name(),
        "items": [],
    }

    for resume in resumes:
        chunk_count = int(
            await db.scalar(
                select(func.count()).select_from(ResumeChunk).where(ResumeChunk.resume_id == resume.id)
            )
            or 0
        )
        indexed_count = int(
            await db.scalar(
                select(func.count())
                .select_from(ResumeChunk)
                .where(ResumeChunk.resume_id == resume.id, ResumeChunk.embedding_status == "indexed")
            )
            or 0
        )
        if only_missing and chunk_count > 0 and indexed_count == chunk_count:
            summary["skipped_count"] += 1
            continue

        result = await reindex_resume_chunks(db, resume)
        result_chunk_count = int(result.get("chunk_count") or 0)
        vector_result = result.get("vector") if isinstance(result.get("vector"), dict) else {}
        vector_status = vector_result.get("status")
        summary["processed_count"] += 1
        summary["chunk_count"] += result_chunk_count
        if vector_status == "success":
            summary["indexed_count"] += result_chunk_count
        elif vector_status == "failed":
            summary["failed_count"] += 1
        if len(summary["items"]) < 50:
            summary["items"].append(
                {
                    "resume_id": str(resume.id),
                    "title": resume.title,
                    "status": result.get("status"),
                    "chunk_count": result_chunk_count,
                    "vector_status": vector_status,
                    "vector_error": vector_result.get("error"),
                }
            )
    if summary["failed_count"]:
        summary["status"] = "partial_failed"
    return summary


def _score_resume_chunk(query_terms: list[str], chunk: ResumeChunk) -> float:
    haystack = " ".join(
        [
            SECTION_LABELS.get(chunk.section, chunk.section),
            chunk.item_title,
            " ".join(chunk.keywords or []),
            chunk.content,
        ]
    ).lower()
    score = 0.0
    for term in query_terms:
        if term in haystack:
            score += 1.0
            if term in " ".join(chunk.keywords or []).lower():
                score += 1.2
            if term in chunk.item_title.lower():
                score += 0.6
    if score > 0 and chunk.section in {"project", "experience"}:
        score += 0.2
    return score


async def _retrieve_resume_keyword_chunks(
    db: AsyncSession,
    *,
    user_id: Any,
    resume_id: Any,
    query: str,
    sections: list[str] | None,
    limit: int,
) -> list[ResumeSnippet]:
    query_terms = normalize_terms(query)
    stmt = select(ResumeChunk).where(ResumeChunk.user_id == user_id, ResumeChunk.resume_id == resume_id)
    if sections:
        stmt = stmt.where(ResumeChunk.section.in_(sections))
    chunks = (await db.execute(stmt)).scalars().all()
    snippets: list[ResumeSnippet] = []
    for chunk in chunks:
        score = _score_resume_chunk(query_terms, chunk)
        if score <= 0:
            continue
        snippets.append(
            ResumeSnippet(
                chunk_id=str(chunk.id),
                resume_id=str(chunk.resume_id),
                section=chunk.section,
                item_title=chunk.item_title,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                keywords=chunk.keywords or [],
                score=score,
                retrieval_source="keyword",
            )
        )
    snippets.sort(key=lambda item: item.score, reverse=True)
    return snippets[:limit]


def _vector_payload_to_resume_snippet(payload: dict[str, Any]) -> ResumeSnippet:
    return ResumeSnippet(
        chunk_id=str(payload.get("chunk_id") or ""),
        resume_id=str(payload.get("resume_id") or ""),
        section=str(payload.get("section") or ""),
        item_title=str(payload.get("item_title") or ""),
        chunk_index=int(payload.get("chunk_index") or 1),
        content=str(payload.get("content") or ""),
        keywords=list(payload.get("keywords") or []),
        score=float(payload.get("score") or 0),
        retrieval_source="vector",
    )


def _merge_resume_snippets(
    vector_snippets: list[ResumeSnippet],
    keyword_snippets: list[ResumeSnippet],
    limit: int,
) -> list[ResumeSnippet]:
    if not vector_snippets:
        return keyword_snippets[:limit]
    if not keyword_snippets:
        return vector_snippets[:limit]

    by_key: dict[str, ResumeSnippet] = {}
    combined_scores: dict[str, float] = {}
    sources: dict[str, set[str]] = {}
    for weight, snippets in [(1.0, vector_snippets), (0.9, keyword_snippets)]:
        for rank, snippet in enumerate(snippets, 1):
            key = snippet.chunk_id
            by_key.setdefault(key, snippet)
            combined_scores[key] = combined_scores.get(key, 0.0) + weight / (60 + rank)
            sources.setdefault(key, set()).add(snippet.retrieval_source)

    merged = list(by_key.items())
    merged.sort(key=lambda item: combined_scores[item[0]], reverse=True)
    result: list[ResumeSnippet] = []
    for key, snippet in merged[:limit]:
        snippet.score = round(combined_scores[key] * 1000, 3)
        snippet.retrieval_source = "+".join(sorted(sources.get(key, {snippet.retrieval_source})))
        result.append(snippet)
    return result


async def retrieve_resume_evidence(
    db: AsyncSession,
    *,
    user_id: Any,
    resume_id: Any,
    query: str,
    sections: list[str] | None = None,
    limit: int = 5,
) -> list[ResumeSnippet]:
    keyword_snippets = await _retrieve_resume_keyword_chunks(
        db,
        user_id=user_id,
        resume_id=resume_id,
        query=query,
        sections=sections,
        limit=max(limit * 2, limit),
    )
    filters = {"doc_type": "resume", "user_id": str(user_id), "resume_id": str(resume_id)}
    vector_payloads = await search_vector_payloads(
        _resume_collection_name(),
        query,
        filters=filters,
        limit=max(limit * 3, limit),
    )
    vector_snippets = [
        _vector_payload_to_resume_snippet(payload)
        for payload in vector_payloads
        if not sections or payload.get("section") in sections
    ][: max(limit * 2, limit)]
    settings = _settings()
    rerank_candidate_limit = max(limit, settings.RERANK_TOP_K)
    merged = _merge_resume_snippets(vector_snippets, keyword_snippets, max(limit * 3, rerank_candidate_limit))
    if not rerank_enabled() or len(merged) <= 1:
        return merged[:limit]

    candidates = merged[:rerank_candidate_limit]
    documents = [f"{snippet.item_title}\n{snippet.content}" for snippet in candidates]
    order, observation = await asyncio.to_thread(rerank_documents, query, documents)
    reranked = [candidates[index] for index in order if index < len(candidates)]
    for index, snippet in enumerate(reranked, 1):
        snippet.retrieval_source = f"{snippet.retrieval_source}+rerank"
        score_boost = max(0, len(reranked) - index + 1) / max(1, len(reranked))
        snippet.score = round(snippet.score + score_boost, 3)
    if observation.get("fallback_used"):
        return merged[:limit]
    return reranked[:limit]
