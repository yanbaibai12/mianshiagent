import asyncio
import gc
import json
import shutil
import time
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models import KnowledgeChunk, KnowledgeDocument, ResumeChunk
from app.services.embedding_service import embed_query, embed_texts, embedding_status

_client: Any | None = None
_last_sync: dict[str, Any] = {}
_last_error: str | None = None


def _settings():
    return get_settings()


def _is_enabled() -> bool:
    return _settings().VECTOR_STORE_BACKEND.lower().strip() == "qdrant"


def _qdrant_imports():
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.http import models
    except Exception as exc:  # pragma: no cover - optional dependency guard
        raise RuntimeError("qdrant-client is not installed.") from exc
    return QdrantClient, models


def get_qdrant_client():
    global _client
    if _client is not None:
        return _client
    settings = _settings()
    QdrantClient, _ = _qdrant_imports()
    if settings.QDRANT_URL:
        kwargs: dict[str, Any] = {"url": settings.QDRANT_URL, "timeout": settings.QDRANT_TIMEOUT_SECONDS}
        if settings.QDRANT_API_KEY:
            kwargs["api_key"] = settings.QDRANT_API_KEY
        _client = QdrantClient(**kwargs)
    else:
        local_path = Path(settings.QDRANT_LOCAL_PATH or "qdrant_storage").resolve()
        local_path.mkdir(parents=True, exist_ok=True)
        _client = QdrantClient(path=str(local_path), timeout=settings.QDRANT_TIMEOUT_SECONDS)
    return _client


def reset_qdrant_client() -> None:
    global _client
    if _client is not None:
        close = getattr(_client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
    _client = None
    gc.collect()


def _read_local_meta(local_path: Path) -> dict[str, Any]:
    meta_path = local_path / "meta.json"
    if not meta_path.exists():
        return {}
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return meta if isinstance(meta, dict) else {}


def _write_local_meta(local_path: Path, meta: dict[str, Any]) -> None:
    (local_path / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def _local_meta_has_collection(local_path: Path, collection_name: str) -> bool:
    collections = _read_local_meta(local_path).get("collections")
    return isinstance(collections, dict) and collection_name in collections


def _is_empty_directory(path: Path) -> bool:
    try:
        return path.is_dir() and next(path.iterdir(), None) is None
    except (OSError, PermissionError):
        return False


def _purge_local_collection_storage(collection_name: str) -> None:
    settings = _settings()
    if settings.QDRANT_URL:
        return
    local_path = Path(settings.QDRANT_LOCAL_PATH or "qdrant_storage").resolve()
    collection_root = (local_path / "collection").resolve()
    collection_path = (collection_root / collection_name).resolve()
    if collection_root not in collection_path.parents:
        raise RuntimeError("refusing to purge collection outside Qdrant local storage")
    collection_in_meta = _local_meta_has_collection(local_path, collection_name)
    if collection_path.exists():
        if not collection_in_meta and _is_empty_directory(collection_path):
            return
        for attempt in range(8):
            try:
                shutil.rmtree(collection_path)
                break
            except PermissionError:
                if not collection_in_meta and _is_empty_directory(collection_path):
                    return
                if attempt == 7:
                    raise
                gc.collect()
                time.sleep(0.25)

    meta = _read_local_meta(local_path)
    collections = meta.get("collections")
    if isinstance(collections, dict) and collection_name in collections:
        collections.pop(collection_name, None)
        _write_local_meta(local_path, meta)


def _collection_name() -> str:
    return _settings().QDRANT_COLLECTION


def ensure_vector_collection(collection_name: str, *, recreate: bool = False) -> None:
    settings = _settings()
    client = get_qdrant_client()
    _, models = _qdrant_imports()
    exists = client.collection_exists(collection_name)
    if recreate:
        if exists:
            client.delete_collection(collection_name)
            reset_qdrant_client()
            _purge_local_collection_storage(collection_name)
            client = get_qdrant_client()
            exists = client.collection_exists(collection_name)
            if exists:
                client.delete_collection(collection_name)
                reset_qdrant_client()
                _purge_local_collection_storage(collection_name)
                client = get_qdrant_client()
                exists = client.collection_exists(collection_name)
        if exists:
            raise RuntimeError(f"failed to recreate Qdrant collection: {collection_name}")
    if not exists:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(size=settings.QDRANT_VECTOR_SIZE, distance=models.Distance.COSINE),
        )
        return

    try:
        info = client.get_collection(collection_name)
        vector_size = _extract_vector_size(info)
    except Exception:
        vector_size = None
    if vector_size and vector_size != settings.QDRANT_VECTOR_SIZE:
        client.delete_collection(collection_name)
        client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(size=settings.QDRANT_VECTOR_SIZE, distance=models.Distance.COSINE),
        )


def _ensure_collection(*, recreate: bool = False) -> None:
    ensure_vector_collection(_collection_name(), recreate=recreate)


def _extract_vector_size(collection_info: Any) -> int | None:
    vectors = getattr(getattr(getattr(collection_info, "config", None), "params", None), "vectors", None)
    if vectors is None:
        return None
    if isinstance(vectors, dict):
        first = next(iter(vectors.values()), None)
        return getattr(first, "size", None) if first is not None else None
    return getattr(vectors, "size", None)


def _count_points(collection_name: str | None = None) -> int:
    client = get_qdrant_client()
    try:
        return int(client.count(collection_name or _collection_name(), exact=True).count)
    except Exception:
        return 0


def _prune_collection_points(collection_name: str, valid_point_ids: set[str]) -> int:
    client = get_qdrant_client()
    _, models = _qdrant_imports()
    if not client.collection_exists(collection_name):
        return 0

    stale_ids: list[Any] = []
    next_offset: Any | None = None
    while True:
        records, next_offset = client.scroll(
            collection_name=collection_name,
            limit=256,
            offset=next_offset,
            with_payload=False,
            with_vectors=False,
        )
        for record in records:
            point_id = getattr(record, "id", None)
            if point_id is not None and str(point_id) not in valid_point_ids:
                stale_ids.append(point_id)
        if next_offset is None:
            break

    for start in range(0, len(stale_ids), 256):
        batch = stale_ids[start : start + 256]
        client.delete(
            collection_name=collection_name,
            points_selector=models.PointIdsList(points=batch),
            wait=True,
        )
    return len(stale_ids)


def _qdrant_filter(filters: dict[str, Any] | None):
    if not filters:
        return None
    _, models = _qdrant_imports()
    must = [
        models.FieldCondition(key=key, match=models.MatchValue(value=value))
        for key, value in filters.items()
        if value is not None
    ]
    if not must:
        return None
    return models.Filter(must=must)


def _chunk_text(document: KnowledgeDocument, chunk: KnowledgeChunk) -> str:
    keywords = " ".join(chunk.keywords or [])
    tags = " ".join(document.tags or [])
    metadata = chunk.chunk_metadata or {}
    skills = " ".join(metadata.get("skills") or [])
    section = metadata.get("section") or ""
    difficulty = metadata.get("difficulty") or ""
    return (
        f"{document.title}\ncategory:{document.category}\ntags:{tags}\nkeywords:{keywords}\n"
        f"section:{section}\ndifficulty:{difficulty}\nskills:{skills}\n{chunk.content}"
    )


def _payload(document: KnowledgeDocument, chunk: KnowledgeChunk) -> dict[str, Any]:
    metadata = chunk.chunk_metadata or {}
    return {
        "doc_type": metadata.get("doc_type", "knowledge"),
        "document_id": str(document.id),
        "chunk_id": str(chunk.id),
        "title": document.title,
        "category": document.category,
        "source": document.source or "builtin",
        "tags": document.tags or [],
        "keywords": chunk.keywords or [],
        "metadata": metadata,
        "question_id": metadata.get("question_id", ""),
        "section": metadata.get("section", ""),
        "difficulty": metadata.get("difficulty", ""),
        "skills": metadata.get("skills", []),
        "roles": metadata.get("roles", []),
        "source_version": metadata.get("source_version", ""),
        "slice_index": metadata.get("slice_index", 1),
        "slice_count": metadata.get("slice_count", 1),
        "content": chunk.content,
        "sequence": chunk.sequence,
    }


async def _load_chunks(db: AsyncSession) -> list[tuple[KnowledgeDocument, KnowledgeChunk]]:
    result = await db.execute(
        select(KnowledgeDocument)
        .options(selectinload(KnowledgeDocument.chunks))
        .where(KnowledgeDocument.is_active.is_(True))
    )
    rows: list[tuple[KnowledgeDocument, KnowledgeChunk]] = []
    for document in result.scalars().all():
        for chunk in sorted(document.chunks, key=lambda item: item.sequence):
            rows.append((document, chunk))
    return rows


async def sync_knowledge_to_vector_store(
    db: AsyncSession,
    *,
    recreate: bool = False,
    respect_startup_flag: bool = False,
) -> dict[str, Any]:
    global _last_sync, _last_error
    settings = _settings()
    started_at = time.perf_counter()
    if not _is_enabled():
        _last_sync = {"status": "skipped", "reason": "vector store backend is not qdrant"}
        return dict(_last_sync)
    if respect_startup_flag and not settings.QDRANT_SYNC_ON_STARTUP:
        _last_sync = {"status": "skipped", "reason": "QDRANT_SYNC_ON_STARTUP=false"}
        return dict(_last_sync)

    try:
        chunks = await _load_chunks(db)
        expected_count = len(chunks)
        await asyncio.to_thread(_ensure_collection, recreate=recreate)
        if respect_startup_flag and not recreate and expected_count > 0:
            current_count = await asyncio.to_thread(_count_points)
            if current_count >= expected_count:
                _last_sync = {
                    "status": "already_synced",
                    "collection": settings.QDRANT_COLLECTION,
                    "points_count": current_count,
                    "expected_count": expected_count,
                    "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                }
                return dict(_last_sync)

        _, models = _qdrant_imports()
        client = get_qdrant_client()
        batch_size = max(1, settings.EMBEDDING_BATCH_SIZE)
        total = 0
        valid_point_ids = {str(chunk.id) for _, chunk in chunks}
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            texts = [_chunk_text(document, chunk) for document, chunk in batch]
            vectors = await asyncio.to_thread(embed_texts, texts)
            points = [
                models.PointStruct(
                    id=str(chunk.id),
                    vector=vector,
                    payload=_payload(document, chunk),
                )
                for (document, chunk), vector in zip(batch, vectors, strict=True)
            ]
            await asyncio.to_thread(client.upsert, collection_name=settings.QDRANT_COLLECTION, points=points)
            total += len(points)

        pruned_count = await asyncio.to_thread(_prune_collection_points, settings.QDRANT_COLLECTION, valid_point_ids)
        points_count = await asyncio.to_thread(_count_points)
        _last_error = None
        _last_sync = {
            "status": "success",
            "collection": settings.QDRANT_COLLECTION,
            "points_count": points_count,
            "expected_count": expected_count,
            "synced_count": total,
            "pruned_count": pruned_count,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "embedding": embedding_status(),
        }
        return dict(_last_sync)
    except Exception as exc:
        _last_error = f"{type(exc).__name__}: {exc}"
        _last_sync = {
            "status": "failed",
            "error": _last_error,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
        }
        if respect_startup_flag:
            return dict(_last_sync)
        raise


async def search_vector_knowledge(
    query: str,
    *,
    categories: list[str] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    if not _is_enabled():
        return []
    settings = _settings()
    try:
        await asyncio.to_thread(_ensure_collection, recreate=False)
        client = get_qdrant_client()
        vector = await asyncio.to_thread(embed_query, query)
        search_limit = max(limit * 3, limit)
        results = await asyncio.to_thread(
            client.search,
            collection_name=settings.QDRANT_COLLECTION,
            query_vector=vector,
            limit=search_limit,
            with_payload=True,
        )
        category_set = set(categories or [])
        payloads: list[dict[str, Any]] = []
        for item in results:
            payload = dict(item.payload or {})
            if category_set and payload.get("category") not in category_set:
                continue
            payload["score"] = float(getattr(item, "score", 0.0))
            payloads.append(payload)
            if len(payloads) >= limit:
                break
        return payloads
    except Exception as exc:
        global _last_error
        _last_error = f"{type(exc).__name__}: {exc}"
        return []


async def upsert_vector_payloads(
    collection_name: str,
    items: list[tuple[str, str, dict[str, Any]]],
) -> dict[str, Any]:
    """Embed and upsert arbitrary text payloads into a Qdrant collection."""
    if not _is_enabled():
        return {"status": "skipped", "reason": "vector store backend is not qdrant"}
    if not items:
        return {"status": "skipped", "reason": "no_items"}

    started_at = time.perf_counter()
    try:
        await asyncio.to_thread(ensure_vector_collection, collection_name, recreate=False)
        _, models = _qdrant_imports()
        client = get_qdrant_client()
        settings = _settings()
        total = 0
        batch_size = max(1, settings.EMBEDDING_BATCH_SIZE)
        for start in range(0, len(items), batch_size):
            batch = items[start : start + batch_size]
            vectors = await asyncio.to_thread(embed_texts, [text for _, text, _ in batch])
            points = [
                models.PointStruct(id=point_id, vector=vector, payload=payload)
                for (point_id, _, payload), vector in zip(batch, vectors, strict=True)
            ]
            await asyncio.to_thread(client.upsert, collection_name=collection_name, points=points)
            total += len(points)
        return {
            "status": "success",
            "collection": collection_name,
            "upserted_count": total,
            "points_count": await asyncio.to_thread(_count_points, collection_name),
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "embedding": embedding_status(),
        }
    except Exception as exc:
        global _last_error
        _last_error = f"{type(exc).__name__}: {exc}"
        return {
            "status": "failed",
            "collection": collection_name,
            "error": _last_error,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
        }


async def search_vector_payloads(
    collection_name: str,
    query: str,
    *,
    filters: dict[str, Any] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    if not _is_enabled():
        return []
    try:
        await asyncio.to_thread(ensure_vector_collection, collection_name, recreate=False)
        client = get_qdrant_client()
        vector = await asyncio.to_thread(embed_query, query)
        results = await asyncio.to_thread(
            client.search,
            collection_name=collection_name,
            query_vector=vector,
            query_filter=_qdrant_filter(filters),
            limit=limit,
            with_payload=True,
        )
        payloads: list[dict[str, Any]] = []
        for item in results:
            payload = dict(item.payload or {})
            payload["score"] = float(getattr(item, "score", 0.0))
            payloads.append(payload)
        return payloads
    except Exception as exc:
        global _last_error
        _last_error = f"{type(exc).__name__}: {exc}"
        return []


async def delete_vector_payloads(
    collection_name: str,
    *,
    filters: dict[str, Any],
) -> dict[str, Any]:
    if not _is_enabled():
        return {"status": "skipped", "reason": "vector store backend is not qdrant"}
    started_at = time.perf_counter()
    try:
        client = get_qdrant_client()
        exists = await asyncio.to_thread(client.collection_exists, collection_name)
        if not exists:
            return {"status": "skipped", "reason": "collection_not_found", "collection": collection_name}
        _, models = _qdrant_imports()
        selector = models.FilterSelector(filter=_qdrant_filter(filters))
        await asyncio.to_thread(
            client.delete,
            collection_name=collection_name,
            points_selector=selector,
            wait=True,
        )
        return {
            "status": "success",
            "collection": collection_name,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
        }
    except Exception as exc:
        global _last_error
        _last_error = f"{type(exc).__name__}: {exc}"
        return {
            "status": "failed",
            "collection": collection_name,
            "error": _last_error,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
        }


async def vector_store_status(db: AsyncSession | None = None) -> dict[str, Any]:
    settings = _settings()
    document_count = None
    chunk_count = None
    resume_chunk_count = None
    if db is not None:
        document_count = await db.scalar(select(func.count()).select_from(KnowledgeDocument)) or 0
        chunk_count = await db.scalar(select(func.count()).select_from(KnowledgeChunk)) or 0
        resume_chunk_count = await db.scalar(select(func.count()).select_from(ResumeChunk)) or 0
    status = {
        "enabled": _is_enabled(),
        "backend": settings.VECTOR_STORE_BACKEND,
        "collection": settings.QDRANT_COLLECTION,
        "resume_collection": settings.QDRANT_RESUME_COLLECTION,
        "configured_vector_size": settings.QDRANT_VECTOR_SIZE,
        "document_count": document_count,
        "chunk_count": chunk_count,
        "resume_chunk_count": resume_chunk_count,
        "embedding": embedding_status(),
        "last_sync": dict(_last_sync),
        "last_error": _last_error,
        "available": False,
        "points_count": 0,
        "resume_points_count": 0,
        "actual_vector_size": None,
        "resume_actual_vector_size": None,
    }
    if not _is_enabled():
        return status
    try:
        client = get_qdrant_client()
        exists = await asyncio.to_thread(client.collection_exists, settings.QDRANT_COLLECTION)
        if exists:
            info = await asyncio.to_thread(client.get_collection, settings.QDRANT_COLLECTION)
            status["actual_vector_size"] = _extract_vector_size(info)
            status["points_count"] = await asyncio.to_thread(_count_points)
            status["available"] = status["actual_vector_size"] == settings.QDRANT_VECTOR_SIZE
        else:
            status["last_error"] = "collection_not_found"
        resume_exists = await asyncio.to_thread(client.collection_exists, settings.QDRANT_RESUME_COLLECTION)
        if resume_exists:
            resume_info = await asyncio.to_thread(client.get_collection, settings.QDRANT_RESUME_COLLECTION)
            status["resume_actual_vector_size"] = _extract_vector_size(resume_info)
            status["resume_points_count"] = await asyncio.to_thread(_count_points, settings.QDRANT_RESUME_COLLECTION)
    except Exception as exc:
        status["last_error"] = f"{type(exc).__name__}: {exc}"
    return status
