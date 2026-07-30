import threading
import time
from typing import Any

import httpx

from app.config import get_settings


class RerankError(RuntimeError):
    pass


_local_reranker_lock = threading.Lock()
_local_reranker: "_BgeReranker | None" = None
_last_observation: dict[str, Any] = {}


def _settings():
    return get_settings()


def _record_observation(**payload: Any) -> None:
    global _last_observation
    safe_payload = dict(payload)
    safe_payload.pop("documents", None)
    safe_payload.pop("query", None)
    _last_observation = safe_payload


def rerank_enabled() -> bool:
    return _settings().RERANK_PROVIDER.lower().strip() not in {"", "none", "disabled", "off"}


class _BgeReranker:
    def __init__(self) -> None:
        settings = _settings()
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except Exception as exc:  # pragma: no cover - optional runtime
            raise RerankError(
                "Local BGE reranker runtime is not installed. Install torch, transformers, sentencepiece and safetensors."
            ) from exc

        self.torch = torch
        requested_device = settings.RERANK_DEVICE.lower()
        if requested_device.startswith("cuda") and not torch.cuda.is_available():
            requested_device = "cpu"
        self.device = requested_device
        cache_dir = settings.EMBEDDING_CACHE_DIR or "models"
        self.tokenizer = AutoTokenizer.from_pretrained(
            settings.RERANK_MODEL,
            trust_remote_code=True,
            cache_dir=cache_dir,
        )
        self.model = AutoModelForSequenceClassification.from_pretrained(
            settings.RERANK_MODEL,
            trust_remote_code=True,
            cache_dir=cache_dir,
        )
        if settings.RERANK_USE_FP16 and self.device != "cpu":
            self.model = self.model.half()
        self.model.to(self.device)
        self.model.eval()

    def score(self, query: str, documents: list[str]) -> list[float]:
        settings = _settings()
        scores: list[float] = []
        batch_size = max(1, settings.RERANK_BATCH_SIZE)
        max_length = max(128, settings.RERANK_MAX_LENGTH)
        for start in range(0, len(documents), batch_size):
            batch = documents[start : start + batch_size]
            pairs = [[query, document] for document in batch]
            encoded = self.tokenizer(
                pairs,
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )
            encoded = {key: value.to(self.device) for key, value in encoded.items()}
            with self.torch.no_grad():
                output = self.model(**encoded, return_dict=True)
                logits = output.logits.view(-1).detach().cpu().float().tolist()
            scores.extend(float(item) for item in logits)
        return scores


def _get_local_reranker() -> _BgeReranker:
    global _local_reranker
    if _local_reranker is None:
        with _local_reranker_lock:
            if _local_reranker is None:
                _local_reranker = _BgeReranker()
    return _local_reranker


def _rerank_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/rerank"):
        return base
    return f"{base}/rerank"


def _remote_scores(query: str, documents: list[str]) -> list[float]:
    settings = _settings()
    if not settings.RERANK_BASE_URL:
        raise RerankError("RERANK_BASE_URL is required for remote rerank.")
    headers = {"content-type": "application/json"}
    if settings.RERANK_API_KEY:
        headers["authorization"] = f"Bearer {settings.RERANK_API_KEY}"
    response = httpx.post(
        _rerank_url(settings.RERANK_BASE_URL),
        headers=headers,
        json={"model": settings.RERANK_MODEL, "query": query, "documents": documents},
        timeout=settings.RERANK_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    results = payload.get("results") or payload.get("data")
    if not isinstance(results, list):
        raise RerankError("Rerank endpoint response does not contain a results list.")
    scores: list[float] = []
    for item in results:
        if isinstance(item, dict):
            scores.append(float(item.get("relevance_score", item.get("score", 0.0))))
        else:
            scores.append(float(item))
    if len(scores) != len(documents):
        raise RerankError("Rerank endpoint returned mismatched scores.")
    return scores


def rerank_documents(query: str, documents: list[str]) -> tuple[list[int], dict[str, Any]]:
    settings = _settings()
    started_at = time.perf_counter()
    provider = settings.RERANK_PROVIDER.lower().strip()
    fallback_used = False
    failure_reason = None
    try:
        if not rerank_enabled() or not documents:
            order = list(range(len(documents)))
            return order, {"enabled": False, "provider": provider or "none", "fallback_used": False}
        if provider in {"bge_reranker", "bge-reranker", "bge"}:
            scores = _get_local_reranker().score(query, documents)
            provider = "bge_reranker"
        elif provider in {"remote", "openai_compatible"}:
            scores = _remote_scores(query, documents)
            provider = "remote"
        else:
            raise RerankError(f"Unsupported rerank provider: {settings.RERANK_PROVIDER}")
        order = sorted(range(len(documents)), key=lambda index: scores[index], reverse=True)
        return order, {
            "enabled": True,
            "provider": provider,
            "model": settings.RERANK_MODEL,
            "batch_size": settings.RERANK_BATCH_SIZE,
            "max_length": settings.RERANK_MAX_LENGTH,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "fallback_used": False,
            "scores": [round(scores[index], 4) for index in order[:10]],
        }
    except Exception as exc:
        failure_reason = f"{type(exc).__name__}: {exc}"
        if not settings.RERANK_ALLOW_FALLBACK:
            raise
        fallback_used = True
        return list(range(len(documents))), {
            "enabled": True,
            "provider": provider,
            "model": settings.RERANK_MODEL,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "fallback_used": True,
            "failure_reason": failure_reason,
        }
    finally:
        _record_observation(
            enabled=rerank_enabled(),
            provider=provider,
            model=settings.RERANK_MODEL,
            document_count=len(documents),
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
            fallback_used=fallback_used,
            failure_reason=failure_reason,
        )


def rerank_status() -> dict[str, Any]:
    settings = _settings()
    return {
        "enabled": rerank_enabled(),
        "provider": settings.RERANK_PROVIDER,
        "model": settings.RERANK_MODEL,
        "top_k": settings.RERANK_TOP_K,
        "batch_size": settings.RERANK_BATCH_SIZE,
        "max_length": settings.RERANK_MAX_LENGTH,
        "base_url_configured": bool(settings.RERANK_BASE_URL),
        "device": settings.RERANK_DEVICE,
        "allow_fallback": settings.RERANK_ALLOW_FALLBACK,
        "model_loaded": _local_reranker is not None,
        "last_call": dict(_last_observation),
    }
