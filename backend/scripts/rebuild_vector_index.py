import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import async_session_maker, init_db  # noqa: E402
from app.services.vector_store import sync_knowledge_to_vector_store, vector_store_status  # noqa: E402


async def rebuild(recreate: bool) -> dict:
    await init_db()
    async with async_session_maker() as db:
        sync_result = await sync_knowledge_to_vector_store(db, recreate=recreate)
        status = await vector_store_status(db)
        return {"sync": sync_result, "status": status}


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild Qdrant index from SQL knowledge chunks.")
    parser.add_argument("--no-recreate", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(rebuild(recreate=not args.no_recreate))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
