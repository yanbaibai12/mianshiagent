import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import async_session_maker, init_db  # noqa: E402
from app.services.vector_store import search_vector_knowledge, sync_knowledge_to_vector_store, vector_store_status  # noqa: E402


async def rebuild(recreate: bool) -> dict:
    await init_db()
    async with async_session_maker() as db:
        sync_result = await sync_knowledge_to_vector_store(db, recreate=recreate)
        status = await vector_store_status(db)
        probes = []
        for query in ["RAG RRF Qdrant 面试题", "Redis 任务队列 失败重试", "FastAPI 接口 联调 排查"]:
            results = await search_vector_knowledge(query, limit=3)
            probes.append(
                {
                    "query": query,
                    "hit_count": len(results),
                    "top_titles": [item.get("title") for item in results[:3]],
                }
            )
        expected_count = int(sync_result.get("expected_count") or status.get("chunk_count") or 0)
        points_count = int(status.get("points_count") or 0)
        validation = {
            "point_count_ok": expected_count == 0 or points_count >= expected_count,
            "vector_size_ok": status.get("actual_vector_size") in {None, status.get("configured_vector_size")},
            "sample_recall_ok": all(item["hit_count"] > 0 for item in probes) if expected_count else True,
            "probes": probes,
        }
        return {"sync": sync_result, "status": status, "validation": validation}


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild Qdrant index from SQL knowledge chunks.")
    parser.add_argument("--no-recreate", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(rebuild(recreate=not args.no_recreate))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    validation = result.get("validation") or {}
    return 0 if all(validation.get(key, False) for key in ["point_count_ok", "vector_size_ok", "sample_recall_ok"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
