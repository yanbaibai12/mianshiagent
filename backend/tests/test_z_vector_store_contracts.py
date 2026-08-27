import uuid
from types import SimpleNamespace

import pytest

from app.services import vector_store as v


class Models:
    class Distance:
        COSINE = "cosine"

    class VectorParams:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class PointStruct:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class PointIdsList:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class MatchValue:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class FieldCondition:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class Filter:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class FilterSelector:
        def __init__(self, **kw):
            self.__dict__.update(kw)


class Client:
    def __init__(self):
        self.exists = set()
        self.deleted = []
        self.upserts = []
        self.closed = False

    def collection_exists(self, n):
        return n in self.exists

    def create_collection(self, collection_name, **kw):
        self.exists.add(collection_name)

    def delete_collection(self, n):
        self.exists.discard(n)

    def get_collection(self, n):
        return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=8))))

    def count(self, n, exact=True):
        return SimpleNamespace(count=2)

    def scroll(self, **kw):
        return ([SimpleNamespace(id="stale"), SimpleNamespace(id="keep")], None)

    def delete(self, **kw):
        self.deleted.append(kw)

    def upsert(self, **kw):
        self.upserts.append(kw)

    def search(self, **kw):
        return [SimpleNamespace(payload={"name": "item"}, score=0.9)]

    def close(self):
        self.closed = True


def settings(tmp_path, backend="qdrant"):
    return SimpleNamespace(
        VECTOR_STORE_BACKEND=backend,
        QDRANT_URL="http://q",
        QDRANT_API_KEY="k",
        QDRANT_TIMEOUT_SECONDS=2,
        QDRANT_LOCAL_PATH=str(tmp_path),
        QDRANT_VECTOR_SIZE=8,
        QDRANT_COLLECTION="knowledge",
        QDRANT_RESUME_COLLECTION="resumes",
        QDRANT_SYNC_ON_STARTUP=True,
        EMBEDDING_BATCH_SIZE=16,
    )


def test_vector_store_local_helpers_and_collection(tmp_path, monkeypatch):
    s = settings(tmp_path)
    c = Client()
    monkeypatch.setattr(v, "_settings", lambda: s)
    monkeypatch.setattr(v, "_qdrant_imports", lambda: (lambda **kw: c, Models))
    monkeypatch.setattr(v, "_client", None)
    assert v._is_enabled() and v._collection_name() == "knowledge"
    assert v.get_qdrant_client() is c
    v.ensure_vector_collection("knowledge")
    assert "knowledge" in c.exists
    info = SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors={"x": SimpleNamespace(size=8)})))
    assert v._extract_vector_size(info) == 8 and v._extract_vector_size(SimpleNamespace()) is None
    assert v._count_points() == 2
    assert v._prune_collection_points("knowledge", {"keep"}) == 1 and c.deleted
    f = v._qdrant_filter({"user_id": "u", "none": None})
    assert len(f.must) == 1
    assert v._qdrant_filter(None) is None and v._qdrant_filter({"x": None}) is None
    v.reset_qdrant_client()
    assert c.closed and v._client is None

    local = tmp_path / "local"
    local.mkdir()
    assert v._read_local_meta(local) == {}
    v._write_local_meta(local, {"collections": {"a": {}}})
    assert v._local_meta_has_collection(local, "a")
    assert v._is_empty_directory(tmp_path / "empty") is False
    (tmp_path / "empty").mkdir()
    assert v._is_empty_directory(tmp_path / "empty")
    (local / "meta.json").write_text("bad", encoding="utf-8")
    assert v._read_local_meta(local) == {}


def test_vector_payload_helpers():
    doc = SimpleNamespace(
        id=uuid.uuid4(), title="RAG", category="agent", tags=["tag"], source="internal", source_url="url"
    )
    chunk = SimpleNamespace(
        id=uuid.uuid4(),
        document_id=doc.id,
        chunk_index=1,
        sequence=1,
        content="FastAPI Qdrant",
        keywords=["rag"],
        chunk_metadata={"skills": ["python"], "section": "project", "difficulty": "medium"},
    )
    assert "FastAPI" in v._chunk_text(doc, chunk)
    payload = v._payload(doc, chunk)
    assert payload["category"] == "agent" and payload["content"] == "FastAPI Qdrant"


@pytest.mark.asyncio
async def test_vector_payload_operations_and_status(tmp_path, monkeypatch):
    s = settings(tmp_path)
    c = Client()
    c.exists.update({"items", "knowledge", "resumes"})
    monkeypatch.setattr(v, "_settings", lambda: s)
    monkeypatch.setattr(v, "_qdrant_imports", lambda: (object, Models))
    monkeypatch.setattr(v, "get_qdrant_client", lambda: c)
    monkeypatch.setattr(v, "ensure_vector_collection", lambda *a, **k: None)
    monkeypatch.setattr(v, "embed_texts", lambda texts: [[1.0] * 8 for _ in texts])
    monkeypatch.setattr(v, "embed_query", lambda text: [1.0] * 8)
    monkeypatch.setattr(v, "embedding_status", lambda: {"provider": "hash"})
    result = await v.upsert_vector_payloads("items", [("id1", "text", {"x": 1}), ("id2", "text2", {"x": 2})])
    assert result["status"] == "success" and c.upserts
    found = await v.search_vector_payloads("items", "query", filters={"user_id": "u"})
    assert found[0]["score"] == 0.9
    deleted = await v.delete_vector_payloads("items", filters={"user_id": "u"})
    assert deleted["status"] == "success"
    status = await v.vector_store_status()
    assert status["available"] and status["points_count"] == 2

    s.VECTOR_STORE_BACKEND = "keyword"
    assert (await v.upsert_vector_payloads("items", []))["status"] == "skipped"
    assert await v.search_vector_payloads("items", "q") == []
    assert (await v.delete_vector_payloads("items", filters={"x": 1}))["status"] == "skipped"
    assert not (await v.vector_store_status())["enabled"]


@pytest.mark.asyncio
async def test_vector_fail_closed_paths(tmp_path, monkeypatch):
    s = settings(tmp_path)
    monkeypatch.setattr(v, "_settings", lambda: s)
    monkeypatch.setattr(v, "ensure_vector_collection", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    assert (await v.upsert_vector_payloads("items", [("id", "t", {})]))["status"] == "failed"
    assert await v.search_vector_payloads("items", "q") == []
    c = Client()
    monkeypatch.setattr(v, "get_qdrant_client", lambda: c)
    assert (await v.delete_vector_payloads("missing", filters={"x": 1}))["reason"] == "collection_not_found"
