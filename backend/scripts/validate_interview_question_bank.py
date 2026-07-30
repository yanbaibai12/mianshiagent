import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BANK = ROOT / "knowledge" / "agent_interview_question_bank_v1.json"

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


def _load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def validate(path: Path) -> dict[str, Any]:
    payload = _load(path)
    documents = payload.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError("documents must be a non-empty list")
    question_ids: set[str] = set()
    categories: set[str] = set()
    skill_hits: dict[str, int] = {}
    total_questions = 0
    for index, document in enumerate(documents, 1):
        missing = REQUIRED_DOCUMENT_FIELDS - set(document)
        if missing:
            raise ValueError(f"document #{index} missing fields: {sorted(missing)}")
        if not isinstance(document["questions"], list) or len(document["questions"]) == 0:
            raise ValueError(f"document #{index} has no questions")
        categories.add(str(document["category"]))
        for question in document["questions"]:
            total_questions += 1
            missing = REQUIRED_QUESTION_FIELDS - set(question)
            if missing:
                raise ValueError(f"question {question.get('id')} missing fields: {sorted(missing)}")
            qid = str(question["id"])
            if qid in question_ids:
                raise ValueError(f"duplicated question id: {qid}")
            question_ids.add(qid)
            if not isinstance(question["answer_points"], list) or len(question["answer_points"]) < 3:
                raise ValueError(f"question {qid} must contain at least 3 answer_points")
            if not isinstance(question["followups"], list) or len(question["followups"]) < 2:
                raise ValueError(f"question {qid} must contain at least 2 followups")
            for skill in question["skills"]:
                skill_hits[str(skill)] = skill_hits.get(str(skill), 0) + 1
    return {
        "documents": len(documents),
        "questions": total_questions,
        "categories": sorted(categories),
        "top_skills": sorted(skill_hits.items(), key=lambda item: item[1], reverse=True)[:12],
    }


def main() -> int:
    path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_BANK
    result = validate(path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
