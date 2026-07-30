import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("RERANK_PROVIDER", "bge_reranker")
os.environ.setdefault("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
os.environ.setdefault("RERANK_ALLOW_FALLBACK", "false")

from app.services.rerank_service import rerank_documents, rerank_status  # noqa: E402


def main() -> int:
    query = "熟悉 RAG、Qdrant、BGE-M3、混合检索和 RRF 重排"
    documents = [
        "负责简历解析、权限系统和普通 CRUD 接口。",
        "实现 RAG 知识库，使用 Qdrant 存储 BGE-M3 向量，融合 BM25 与向量召回后做 RRF。",
        "参与 React 页面开发，处理表单校验和导出按钮。",
    ]
    order, observation = rerank_documents(query, documents)
    print(json.dumps({"order": order, "observation": observation, "status": rerank_status()}, ensure_ascii=False, indent=2, default=str))
    return 0 if observation.get("enabled") and not observation.get("fallback_used") else 1


if __name__ == "__main__":
    raise SystemExit(main())
