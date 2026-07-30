import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.services.embedding_service import embed_texts, embedding_status  # noqa: E402


def main() -> int:
    settings = get_settings()
    sample = "RAG 混合检索、BGE-M3 embedding、Qdrant 向量库、RRF 倒数排序如何设计？"
    vectors = embed_texts([sample])
    vector = vectors[0]
    payload = {
        "expected_size": settings.QDRANT_VECTOR_SIZE,
        "actual_size": len(vector),
        "status": embedding_status(),
        "preview": vector[:5],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if len(vector) != settings.QDRANT_VECTOR_SIZE:
        print(f"Embedding size mismatch: expected {settings.QDRANT_VECTOR_SIZE}, got {len(vector)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
