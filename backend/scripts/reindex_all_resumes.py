import argparse
import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import async_session_maker, init_db  # noqa: E402
from app.services.resume_index import reindex_all_resume_chunks  # noqa: E402


async def run(*, only_missing: bool, limit: int | None) -> dict:
    await init_db()
    async with async_session_maker() as db:
        result = await reindex_all_resume_chunks(db, only_missing=only_missing, limit=limit)
        await db.commit()
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Reindex existing resumes into the resume vector collection.")
    parser.add_argument("--force", action="store_true", help="Rebuild all selected resumes even if chunks already exist.")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    result = asyncio.run(run(only_missing=not args.force, limit=args.limit))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") in {"success", "partial_failed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
