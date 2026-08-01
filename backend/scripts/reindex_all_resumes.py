import argparse
import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import async_session_maker, init_db  # noqa: E402
from app.services.resume_index import reindex_all_resume_chunks  # noqa: E402
from app.services.vector_store import vector_store_status  # noqa: E402


async def run(*, only_missing: bool, limit: int | None) -> dict:
    await init_db()
    async with async_session_maker() as db:
        result = await reindex_all_resume_chunks(db, only_missing=only_missing, limit=limit)
        await db.commit()
        status = await vector_store_status(db)
        resume_chunk_count = int(status.get("resume_chunk_count") or 0)
        resume_points_count = int(status.get("resume_points_count") or 0)
        result["validation"] = {
            "resume_point_count_ok": resume_chunk_count == 0 or resume_points_count >= resume_chunk_count,
            "resume_vector_size_ok": status.get("resume_actual_vector_size") in {None, status.get("configured_vector_size")},
            "resume_sql_chunks": resume_chunk_count,
            "resume_vector_points": resume_points_count,
        }
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Reindex existing resumes into the resume vector collection.")
    parser.add_argument("--force", action="store_true", help="Rebuild all selected resumes even if chunks already exist.")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    result = asyncio.run(run(only_missing=not args.force, limit=args.limit))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    validation = result.get("validation") or {}
    return 0 if result.get("status") in {"success", "partial_failed"} and all(
        validation.get(key, False) for key in ["resume_point_count_ok", "resume_vector_size_ok"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
