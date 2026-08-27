import json
import re
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import KnowledgeChunk, KnowledgeDocument
from app.services.knowledge_base import _token_estimate
from app.services.vector_store import sync_knowledge_to_vector_store

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INTERVIEW_BANK = ROOT / "knowledge" / "agent_interview_question_bank_v1.json"

REQUIRED_DOCUMENT_FIELDS = {"title", "category", "tags", "questions"}
REQUIRED_QUESTION_FIELDS = {
    "id",
    "section",
    "difficulty",
    "roles",
    "skills",
    "question",
    "focus",
    "scenario",
    "answer_points",
    "followups",
    "scoring",
    "red_flags",
    "keywords",
}

_WHITESPACE_RE = re.compile(r"[ \t\r\f\v]+")


def _clean_text(value: Any, *, max_chars: int = 4000) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\u3000", " ").replace("\ufeff", "")
    text = _WHITESPACE_RE.sub(" ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip(" \n\t,，;；。")
    return text[:max_chars]


def _clean_list(value: Any, *, max_items: int = 30, max_chars: int = 500) -> list[str]:
    if value is None:
        values: list[Any] = []
    elif isinstance(value, list):
        values = value
    else:
        values = [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _clean_text(item, max_chars=max_chars)
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result[:max_items]


def _recursive_split_segment(text: str, max_chars: int, separators: list[str]) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    if not separators:
        return [
            text[index : index + max_chars].strip()
            for index in range(0, len(text), max_chars)
            if text[index : index + max_chars].strip()
        ]

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


def recursive_split_text(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    max_chars = max(400, chunk_size)
    overlap_chars = max(0, min(overlap, max_chars // 3))
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
        chunks.append(f"{prefix}\n{current}".strip() if prefix else current)
    return chunks


def _load_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError("question bank root must be an object")
    return payload


def normalize_question_bank(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    source = _clean_text(payload.get("source") or "agent_question_bank", max_chars=120)
    version = _clean_text(payload.get("version") or "unknown", max_chars=60)
    documents = payload.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError("documents must be a non-empty list")

    normalized_documents: list[dict[str, Any]] = []
    seen_question_keys: set[str] = set()
    duplicate_count = 0
    cleaned_questions = 0

    for index, document in enumerate(documents, 1):
        if not isinstance(document, dict):
            raise ValueError(f"document #{index} must be an object")
        missing = REQUIRED_DOCUMENT_FIELDS - set(document)
        if missing:
            raise ValueError(f"document #{index} missing fields: {sorted(missing)}")

        questions = document.get("questions")
        if not isinstance(questions, list) or not questions:
            raise ValueError(f"document #{index} has no questions")

        normalized_questions: list[dict[str, Any]] = []
        for question in questions:
            if not isinstance(question, dict):
                raise ValueError(f"question in document #{index} must be an object")
            missing = REQUIRED_QUESTION_FIELDS - set(question)
            if missing:
                raise ValueError(f"question {question.get('id')} missing fields: {sorted(missing)}")

            normalized_question = {
                "id": _clean_text(question["id"], max_chars=80),
                "section": _clean_text(question["section"], max_chars=80),
                "difficulty": _clean_text(question["difficulty"], max_chars=40),
                "roles": _clean_list(question["roles"], max_items=12, max_chars=80),
                "skills": _clean_list(question["skills"], max_items=20, max_chars=80),
                "question": _clean_text(question["question"], max_chars=800),
                "focus": _clean_text(question["focus"], max_chars=800),
                "scenario": _clean_text(question["scenario"], max_chars=1000),
                "answer_points": _clean_list(question["answer_points"], max_items=12, max_chars=600),
                "followups": _clean_list(question["followups"], max_items=10, max_chars=400),
                "scoring": _clean_list(question["scoring"], max_items=10, max_chars=400),
                "red_flags": _clean_list(question["red_flags"], max_items=10, max_chars=300),
                "keywords": _clean_list(question["keywords"], max_items=30, max_chars=80),
            }
            if not normalized_question["id"] or not normalized_question["question"]:
                raise ValueError(f"question in document #{index} has empty id or question")
            if len(normalized_question["answer_points"]) < 3:
                raise ValueError(f"question {normalized_question['id']} must contain at least 3 answer_points")
            if len(normalized_question["followups"]) < 2:
                raise ValueError(f"question {normalized_question['id']} must contain at least 2 followups")

            question_text_key = normalized_question["question"].lower()
            if normalized_question["id"].lower() in seen_question_keys or question_text_key in seen_question_keys:
                duplicate_count += 1
                continue
            seen_question_keys.add(normalized_question["id"].lower())
            seen_question_keys.add(question_text_key)
            normalized_questions.append(normalized_question)
            cleaned_questions += 1

        if not normalized_questions:
            raise ValueError(f"document #{index} has no valid questions after cleaning")

        normalized_documents.append(
            {
                "title": _clean_text(document["title"], max_chars=200),
                "category": _clean_text(document["category"], max_chars=80),
                "source": _clean_text(document.get("source") or source, max_chars=200),
                "tags": _clean_list(document.get("tags", []), max_items=30, max_chars=80),
                "questions": normalized_questions,
            }
        )

    normalized = {"source": source, "version": version, "documents": normalized_documents}
    stats = {
        "source": source,
        "version": version,
        "documents": len(normalized_documents),
        "questions": cleaned_questions,
        "duplicates_removed": duplicate_count,
    }
    return normalized, stats


def load_agent_question_cards(path: Path = DEFAULT_INTERVIEW_BANK) -> list[dict[str, Any]]:
    payload, _stats = normalize_question_bank(_load_payload(path))
    cards: list[dict[str, Any]] = []
    for document in payload["documents"]:
        for question in document["questions"]:
            cards.append(
                {
                    **question,
                    "source_title": document["title"],
                    "category": document["category"],
                    "tags": document["tags"],
                    "source": document.get("source") or payload["source"],
                    "source_version": payload["version"],
                }
            )
    return cards


def question_bank_filter_options(cards: list[dict[str, Any]]) -> dict[str, list[str]]:
    def unique(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            text = _clean_text(value, max_chars=80)
            key = text.lower()
            if text and key not in seen:
                seen.add(key)
                result.append(text)
        return sorted(result)

    roles: list[str] = []
    skills: list[str] = []
    sections: list[str] = []
    difficulties: list[str] = []
    for card in cards:
        sections.append(str(card.get("section") or ""))
        difficulties.append(str(card.get("difficulty") or ""))
        roles.extend(str(item) for item in card.get("roles") or [])
        skills.extend(str(item) for item in card.get("skills") or [])
    return {
        "sections": unique(sections),
        "difficulties": unique(difficulties),
        "roles": unique(roles),
        "skills": unique(skills),
    }


def filter_agent_question_cards(
    cards: list[dict[str, Any]],
    *,
    query: str | None = None,
    section: str | None = None,
    difficulty: str | None = None,
    role: str | None = None,
    skill: str | None = None,
) -> list[dict[str, Any]]:
    query_text = _clean_text(query, max_chars=200).lower()
    section_text = _clean_text(section, max_chars=80).lower()
    difficulty_text = _clean_text(difficulty, max_chars=40).lower()
    role_text = _clean_text(role, max_chars=80).lower()
    skill_text = _clean_text(skill, max_chars=80).lower()

    result: list[dict[str, Any]] = []
    for card in cards:
        roles = [str(item).lower() for item in card.get("roles") or []]
        skills = [str(item).lower() for item in card.get("skills") or []]
        if section_text and str(card.get("section") or "").lower() != section_text:
            continue
        if difficulty_text and str(card.get("difficulty") or "").lower() != difficulty_text:
            continue
        if role_text and role_text not in roles:
            continue
        if skill_text and skill_text not in skills:
            continue
        if query_text:
            search_text = json.dumps(card, ensure_ascii=False).lower()
            if query_text not in search_text:
                continue
        result.append(card)
    return result


def _question_to_content(question: dict[str, Any]) -> str:
    answer_points = "\n".join(f"- {item}" for item in question["answer_points"])
    followups = "\n".join(f"- {item}" for item in question["followups"])
    scoring = "\n".join(f"- {item}" for item in question["scoring"])
    red_flags = "\n".join(f"- {item}" for item in question["red_flags"])
    return "\n".join(
        [
            f"题目：{question['question']}",
            f"考察重点：{question['focus']}",
            f"业务/项目情景：{question['scenario']}",
            f"参考答题要点：\n{answer_points}",
            f"可追问：\n{followups}",
            f"评分标准：\n{scoring}",
            f"危险信号：\n{red_flags}",
            f"难度：{question['difficulty']}；方向：{question['section']}；适配角色：{'、'.join(question['roles'])}",
        ]
    )


def _question_keywords(document: dict[str, Any], question: dict[str, Any]) -> list[str]:
    return _clean_list(
        [
            *document.get("tags", []),
            *question.get("skills", []),
            *question.get("keywords", []),
            question.get("section", ""),
            question.get("difficulty", ""),
            *question.get("roles", []),
        ],
        max_items=50,
        max_chars=80,
    )


def _chunk_metadata(
    payload: dict[str, Any],
    document: dict[str, Any],
    question: dict[str, Any],
    *,
    slice_index: int,
    slice_count: int,
) -> dict[str, Any]:
    return {
        "doc_type": "interview_question",
        "question_id": question["id"],
        "section": question["section"],
        "difficulty": question["difficulty"],
        "roles": question["roles"],
        "skills": question["skills"],
        "keywords": question["keywords"],
        "focus": question["focus"],
        "scenario": question["scenario"],
        "source": document.get("source") or payload["source"],
        "source_version": payload["version"],
        "source_title": document["title"],
        "chunk_type": "question_card",
        "slice_index": slice_index,
        "slice_count": slice_count,
    }


def _stable_chunk_id(document_title: str, question_id: str, slice_index: int) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"mianshiagent:knowledge:{document_title}:{question_id}:{slice_index}")


def validate_question_bank(path: Path = DEFAULT_INTERVIEW_BANK) -> dict[str, Any]:
    normalized, stats = normalize_question_bank(_load_payload(path))
    skill_hits: dict[str, int] = {}
    sections: set[str] = set()
    difficulties: set[str] = set()
    categories: set[str] = set()
    for document in normalized["documents"]:
        categories.add(document["category"])
        for question in document["questions"]:
            sections.add(question["section"])
            difficulties.add(question["difficulty"])
            for skill in question["skills"]:
                skill_hits[skill] = skill_hits.get(skill, 0) + 1
    return {
        **stats,
        "categories": sorted(categories),
        "sections": sorted(sections),
        "difficulties": sorted(difficulties),
        "top_skills": sorted(skill_hits.items(), key=lambda item: item[1], reverse=True)[:12],
    }


async def import_interview_question_bank(
    db: AsyncSession,
    path: Path = DEFAULT_INTERVIEW_BANK,
    *,
    skip_vector: bool = False,
    recreate_vector: bool = False,
) -> dict[str, Any]:
    payload, stats = normalize_question_bank(_load_payload(path))
    settings = get_settings()
    imported_documents = 0
    imported_questions = 0
    imported_chunks = 0

    for document_data in payload["documents"]:
        title = str(document_data["title"])
        result = await db.execute(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.title == title)
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.category = document_data["category"]
            existing.source = document_data.get("source") or payload["source"]
            existing.tags = document_data.get("tags", [])
            existing.is_active = True
            document = existing
        else:
            document = KnowledgeDocument(
                title=title,
                category=document_data["category"],
                source=document_data.get("source") or payload["source"],
                tags=document_data.get("tags", []),
                is_builtin=False,
                is_active=True,
            )
            db.add(document)
        await db.flush()
        await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id))

        sequence = 1
        for question in document_data["questions"]:
            card_content = _question_to_content(question)
            slices = recursive_split_text(
                card_content,
                chunk_size=settings.KNOWLEDGE_CHUNK_SIZE,
                overlap=settings.KNOWLEDGE_CHUNK_OVERLAP,
            )
            imported_questions += 1
            for slice_index, slice_text in enumerate(slices, 1):
                metadata = _chunk_metadata(
                    payload,
                    document_data,
                    question,
                    slice_index=slice_index,
                    slice_count=len(slices),
                )
                db.add(
                    KnowledgeChunk(
                        id=_stable_chunk_id(document_data["title"], question["id"], slice_index),
                        document_id=document.id,
                        sequence=sequence,
                        content=slice_text,
                        keywords=_question_keywords(document_data, question),
                        chunk_metadata=metadata,
                        token_estimate=_token_estimate(slice_text),
                    )
                )
                sequence += 1
                imported_chunks += 1
        imported_documents += 1

    await db.commit()
    vector_result = None
    if not skip_vector:
        vector_result = await sync_knowledge_to_vector_store(db, recreate=recreate_vector)
    return {
        **stats,
        "documents": imported_documents,
        "questions": imported_questions,
        "chunks": imported_chunks,
        "skip_vector": skip_vector,
        "recreate_vector": recreate_vector,
        "path": str(path),
        "vector_sync": vector_result,
    }
