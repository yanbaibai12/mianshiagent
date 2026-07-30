import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("VECTOR_STORE_BACKEND", "keyword")
os.environ.setdefault("QDRANT_SYNC_ON_STARTUP", "false")
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")

from app.database import async_session_maker, init_db  # noqa: E402
from app.services.knowledge_base import retrieve_knowledge  # noqa: E402
from app.services.vector_store import vector_store_status  # noqa: E402

CASES = [
    ("RRF 倒数排序怎么追问", ["RRF", "倒数排序", "融合"]),
    ("混合检索 BM25 和向量召回如何设计", ["混合检索", "BM25", "向量"]),
    ("Qdrant 向量库怎么重建索引", ["Qdrant", "索引", "重建"]),
    ("BGE-M3 embedding 1024 维怎么排查", ["BGE-M3", "1024", "维度"]),
    ("RAG 递归切片怎么避免语义断裂", ["切片", "语义", "chunk"]),
    ("rerank 在 RAG 里什么时候使用", ["rerank", "排序", "召回"]),
    ("Agent 工具调用失败怎么处理", ["工具调用", "失败", "重试"]),
    ("Function Calling 参数校验怎么设计", ["Function Calling", "参数", "schema"]),
    ("ReAct Agent 如何避免无限循环", ["ReAct", "循环", "终止"]),
    ("Prompt Injection 怎么防护", ["Prompt Injection", "防护", "权限"]),
    ("FastAPI 长任务进度条怎么设计", ["FastAPI", "任务", "进度"]),
    ("Redis 队列任务失败重试怎么做", ["Redis", "重试", "队列"]),
    ("PostgreSQL 慢查询和索引如何复盘", ["PostgreSQL", "索引", "慢查询"]),
    ("接口幂等性在简历优化任务里怎么设计", ["幂等", "任务", "接口"]),
    ("LLM 质量评测集怎么防止套话", ["评测集", "套话", "回归"]),
    ("简历 JD 优化不能编造经历怎么控制", ["简历", "JD", "编造"]),
    ("面试题如何覆盖项目实习和技术八股", ["项目", "实习", "八股"]),
    ("结构化日志 request_id 怎么串联排查", ["request_id", "日志", "排查"]),
    ("RAG 召回没有项目问题怎么修复", ["RAG", "项目", "召回"]),
    ("Agent 记忆模块怎么控制隐私风险", ["记忆", "隐私", "风险"]),
]


def _hit(text: str, expected_terms: list[str]) -> bool:
    normalized = text.lower()
    return any(term.lower() in normalized for term in expected_terms)


async def run_eval(limit: int = 5) -> dict:
    await init_db()
    async with async_session_maker() as db:
        results = []
        passed = 0
        for query, expected_terms in CASES:
            snippets = await retrieve_knowledge(db, query, limit=limit)
            joined = "\n".join(
                f"{snippet.title}\n{' '.join(snippet.keywords)}\n{snippet.content}" for snippet in snippets
            )
            ok = _hit(joined, expected_terms)
            passed += 1 if ok else 0
            results.append(
                {
                    "query": query,
                    "passed": ok,
                    "expected_terms": expected_terms,
                    "top_results": [
                        {
                            "title": snippet.title,
                            "category": snippet.category,
                            "score": snippet.score,
                            "keywords": snippet.keywords[:8],
                        }
                        for snippet in snippets[:3]
                    ],
                }
            )
        status = await vector_store_status(db)
        return {
            "passed": passed,
            "total": len(CASES),
            "pass_rate": round(passed / len(CASES), 4),
            "vector_store": status,
            "results": results,
        }


def main() -> int:
    result = asyncio.run(run_eval())
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["pass_rate"] >= 0.9 else 1


if __name__ == "__main__":
    raise SystemExit(main())
