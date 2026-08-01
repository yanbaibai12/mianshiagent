import hashlib
import math
import os
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings


class EmbeddingError(RuntimeError):
    pass


_local_model_lock = threading.Lock()
_local_model: "_BgeM3TransformersModel | None" = None
_last_observation: dict[str, Any] = {}


def _settings():
    return get_settings()


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [value / norm for value in vector]


def _hash_embedding(text: str, size: int) -> list[float]:
    values = [0.0] * size
    tokens = text.lower().split()
    if not tokens:
        tokens = [text.lower() or "empty"]
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8", errors="ignore"), digest_size=16).digest()
        for offset in range(0, len(digest), 2):
            bucket = int.from_bytes(digest[offset : offset + 2], "big") % size
            values[bucket] += 1.0 if digest[offset] % 2 == 0 else -1.0
    return _normalize(values)


def _record_observation(**payload: Any) -> None:
    global _last_observation
    safe_payload = dict(payload)
    safe_payload.pop("text", None)
    safe_payload.pop("texts", None)
    _last_observation = safe_payload


def _validate_vectors(vectors: list[list[float]], expected_size: int) -> None:
    for vector in vectors:
        if len(vector) != expected_size:
            raise EmbeddingError(f"Embedding vector size mismatch: expected {expected_size}, got {len(vector)}")


class _BgeM3TransformersModel:
    def __init__(self) -> None:
        settings = _settings()
        cache_dir = Path(settings.EMBEDDING_CACHE_DIR).resolve()
        cache_dir.mkdir(parents=True, exist_ok=True)
        if settings.EMBEDDING_HF_ENDPOINT:
            os.environ.setdefault("HF_ENDPOINT", settings.EMBEDDING_HF_ENDPOINT)
        os.environ.setdefault("HF_HOME", str(cache_dir))
        os.environ.setdefault("TRANSFORMERS_CACHE", str(cache_dir))

        try:
            import torch
            import torch.nn.functional as functional
            from transformers import AutoModel, AutoTokenizer
        except Exception as exc:  # pragma: no cover - depends on optional local runtime
            raise EmbeddingError(
                "Local BGE-M3 runtime is not installed. Install torch, transformers, sentencepiece and safetensors."
            ) from exc

        self.torch = torch
        self.functional = functional
        requested_device = settings.EMBEDDING_DEVICE.lower()
        if requested_device.startswith("cuda") and not torch.cuda.is_available():
            requested_device = "cpu"
        self.device = requested_device
        self.tokenizer = AutoTokenizer.from_pretrained(
            settings.EMBEDDING_MODEL,
            trust_remote_code=True,
            cache_dir=str(cache_dir),
        )
        self.model = AutoModel.from_pretrained(
            settings.EMBEDDING_MODEL,
            trust_remote_code=True,
            cache_dir=str(cache_dir),
        )
        if settings.EMBEDDING_USE_FP16 and self.device != "cpu":
            self.model = self.model.half()
        self.model.to(self.device)
        self.model.eval()

    def encode(self, texts: list[str]) -> list[list[float]]:
        settings = _settings()
        encoded = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=settings.EMBEDDING_MAX_LENGTH,
            return_tensors="pt",
        )
        encoded = {key: value.to(self.device) for key, value in encoded.items()}
        with self.torch.no_grad():
            output = self.model(**encoded, return_dict=True)
            embeddings = output.last_hidden_state[:, 0]
            embeddings = self.functional.normalize(embeddings, p=2, dim=1)
        return embeddings.detach().cpu().float().tolist()


def _get_local_model() -> _BgeM3TransformersModel:
    global _local_model
    if _local_model is None:
        with _local_model_lock:
            if _local_model is None:
                _local_model = _BgeM3TransformersModel()
    return _local_model


def _embedding_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/embeddings"):
        return base
    return f"{base}/embeddings"


def _embed_remote(texts: list[str]) -> list[list[float]]:
    settings = _settings()
    if not settings.EMBEDDING_BASE_URL:
        raise EmbeddingError("EMBEDDING_BASE_URL is required for remote embeddings.")
    headers = {"content-type": "application/json"}
    if settings.EMBEDDING_API_KEY:
        headers["authorization"] = f"Bearer {settings.EMBEDDING_API_KEY}"
    response = httpx.post(
        _embedding_url(settings.EMBEDDING_BASE_URL),
        headers=headers,
        json={"model": settings.EMBEDDING_MODEL, "input": texts},
        timeout=settings.EMBEDDING_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data")
    if not isinstance(data, list):
        raise EmbeddingError("Embedding endpoint response does not contain a data list.")
    vectors = [item.get("embedding") for item in data if isinstance(item, dict)]
    if len(vectors) != len(texts) or not all(isinstance(item, list) for item in vectors):
        raise EmbeddingError("Embedding endpoint returned invalid vectors.")
    return vectors


def embed_texts(texts: list[str]) -> list[list[float]]:
    settings = _settings()
    started_at = time.perf_counter()
    provider = settings.EMBEDDING_PROVIDER.lower().strip()
    fallback_used = False
    failure_reason = None
    try:
        if provider == "hash" or settings.VECTOR_STORE_BACKEND.lower() == "keyword":
            vectors = [_hash_embedding(text, settings.QDRANT_VECTOR_SIZE) for text in texts]
        elif provider in {"openai_compatible", "remote"} or settings.EMBEDDING_BASE_URL:
            vectors = _embed_remote(texts)
        elif provider in {"bge_m3", "bge-m3", "bge_m3_transformers"}:
            vectors = _get_local_model().encode(texts)
            provider = "bge_m3_transformers"
        else:
            raise EmbeddingError(f"Unsupported embedding provider: {settings.EMBEDDING_PROVIDER}")
        _validate_vectors(vectors, settings.QDRANT_VECTOR_SIZE)
        return vectors
    except Exception as exc:
        failure_reason = type(exc).__name__
        if not settings.EMBEDDING_ALLOW_FALLBACK:
            raise
        fallback_used = True
        provider = f"{provider}->hash"
        vectors = [_hash_embedding(text, settings.QDRANT_VECTOR_SIZE) for text in texts]
        return vectors
    finally:
        _record_observation(
            provider=provider,
            model=settings.EMBEDDING_MODEL,
            batch_size=len(texts),
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
            fallback_used=fallback_used,
            failure_reason=failure_reason,
            vector_size=settings.QDRANT_VECTOR_SIZE,
        )


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


def embedding_status() -> dict[str, Any]:
    settings = _settings()
    provider = settings.EMBEDDING_PROVIDER.lower().strip()
    active_provider = "keyword" if settings.VECTOR_STORE_BACKEND.lower() == "keyword" else provider
    return {
        "provider": active_provider,
        "model": settings.EMBEDDING_MODEL,
        "vector_size": settings.QDRANT_VECTOR_SIZE,
        "base_url_configured": bool(settings.EMBEDDING_BASE_URL),
        "local_cache_dir": str(Path(settings.EMBEDDING_CACHE_DIR).resolve()),
        "device": settings.EMBEDDING_DEVICE,
        "hf_endpoint": settings.EMBEDDING_HF_ENDPOINT,
        "allow_fallback": settings.EMBEDDING_ALLOW_FALLBACK,
        "model_loaded": _local_model is not None,
        "last_call": dict(_last_observation),
    }


def embedding_probe(sample_text: str = "BGE-M3 embedding health probe") -> dict[str, Any]:
    settings = _settings()
    started_at = time.perf_counter()
    try:
        vector = embed_query(sample_text)
        actual_size = len(vector)
        return {
            "ok": actual_size == settings.QDRANT_VECTOR_SIZE,
            "provider": embedding_status()["provider"],
            "model": settings.EMBEDDING_MODEL,
            "expected_vector_size": settings.QDRANT_VECTOR_SIZE,
            "actual_vector_size": actual_size,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "fallback_used": bool((embedding_status().get("last_call") or {}).get("fallback_used")),
            "failure_reason": (embedding_status().get("last_call") or {}).get("failure_reason"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "provider": embedding_status()["provider"],
            "model": settings.EMBEDDING_MODEL,
            "expected_vector_size": settings.QDRANT_VECTOR_SIZE,
            "actual_vector_size": 0,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "fallback_used": False,
            "failure_reason": f"{type(exc).__name__}: {exc}",
        }
