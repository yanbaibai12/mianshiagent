import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import async_session_maker, init_db  # noqa: E402
from app.models import KnowledgeChunk, KnowledgeDocument  # noqa: E402
from app.services.knowledge_base import _token_estimate  # noqa: E402
from app.services.vector_store import sync_knowledge_to_vector_store  # noqa: E402

DEFAULT_BANK = ROOT / "knowledge" / "agent_interview_question_bank_v1.json"


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
    keywords: list[str] = []
    for value in [*document.get("tags", []), *question.get("skills", []), *question.get("keywords", [])]:
        text = str(value).strip()
        if text and text not in keywords:
            keywords.append(text)
    return keywords[:40]


async def import_bank(path: Path, *, skip_vector: bool, recreate_vector: bool) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    documents = payload.get("documents", [])
    await init_db()
    async with async_session_maker() as db:
        imported_documents = 0
        imported_questions = 0
        for document_data in documents:
            source = document_data.get("source") or payload.get("source") or "agent_question_bank_v1"
            title = str(document_data["title"])
            result = await db.execute(
                select(KnowledgeDocument)
                .options(selectinload(KnowledgeDocument.chunks))
                .where(KnowledgeDocument.title == title)
            )
            existing = result.scalar_one_or_none()
            if existing:
                await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == existing.id))
                existing.category = document_data["category"]
                existing.source = source
                existing.tags = document_data.get("tags", [])
                existing.is_active = True
                document = existing
            else:
                document = KnowledgeDocument(
                    title=title,
                    category=document_data["category"],
                    source=source,
                    tags=document_data.get("tags", []),
                    is_builtin=False,
                    is_active=True,
                )
                db.add(document)
            for sequence, question in enumerate(document_data["questions"], 1):
                content = _question_to_content(question)
                document.chunks.append(
                    KnowledgeChunk(
                        sequence=sequence,
                        content=content,
                        keywords=_question_keywords(document_data, question),
                        token_estimate=_token_estimate(content),
                    )
                )
                imported_questions += 1
            imported_documents += 1
        await db.commit()
        vector_result = None
        if not skip_vector:
            vector_result = await sync_knowledge_to_vector_store(db, recreate=recreate_vector)
        return {
            "documents": imported_documents,
            "questions": imported_questions,
            "source": payload.get("source") or "agent_question_bank_v1",
            "vector_sync": vector_result,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import structured Agent interview question cards into the knowledge base.")
    parser.add_argument("path", nargs="?", default=str(DEFAULT_BANK))
    parser.add_argument("--skip-vector", action="store_true")
    parser.add_argument("--recreate-vector", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(import_bank(Path(args.path).resolve(), skip_vector=args.skip_vector, recreate_vector=args.recreate_vector))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
