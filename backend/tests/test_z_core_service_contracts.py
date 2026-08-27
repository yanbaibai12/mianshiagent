import io
import math
import sys
import types
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, UploadFile

from app.services import company_profiles as cp
from app.services import embedding_service as emb
from app.services import rerank_service as rr
from app.services import resume_index as ri
from app.services.resume_parser import ResumeParser
from app.services.resume_versions import build_version_compare, ensure_original_version
from app.utils import storage
from app.utils.json_extract import extract_json, safe_get


def embedding_settings(**overrides):
    values = dict(
        EMBEDDING_PROVIDER="hash",
        VECTOR_STORE_BACKEND="qdrant",
        QDRANT_VECTOR_SIZE=8,
        EMBEDDING_MODEL="test-embedding",
        EMBEDDING_BASE_URL="",
        EMBEDDING_API_KEY="",
        EMBEDDING_TIMEOUT_SECONDS=3,
        EMBEDDING_ALLOW_FALLBACK=False,
        EMBEDDING_CACHE_DIR="models",
        EMBEDDING_DEVICE="cpu",
        EMBEDDING_HF_ENDPOINT="",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def rerank_settings(**overrides):
    values = dict(
        RERANK_PROVIDER="none",
        RERANK_MODEL="test-reranker",
        RERANK_BASE_URL="",
        RERANK_API_KEY="",
        RERANK_TIMEOUT_SECONDS=3,
        RERANK_ALLOW_FALLBACK=False,
        RERANK_BATCH_SIZE=2,
        RERANK_MAX_LENGTH=512,
        RERANK_TOP_K=5,
        RERANK_DEVICE="cpu",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_json_extract_accepts_fenced_embedded_and_rejects_invalid():
    assert extract_json('```json\n{"ok": true}\n```') == {"ok": True}
    assert extract_json("prefix [1, 2, 3] suffix") == [1, 2, 3]
    assert extract_json('before {"a": 1} after') == {"a": 1}
    with pytest.raises(ValueError, match="无法从"):
        extract_json("not-json")
    assert safe_get({"x": None}, "x", "fallback") is None
    assert safe_get({}, "x", "fallback") == "fallback"


def test_storage_content_validation_and_safe_delete(tmp_path, monkeypatch):
    assert storage.get_file_extension("CV.PDF") == ".pdf"
    assert storage.is_allowed_file("cv.docx")
    assert not storage.is_allowed_file("cv.exe")
    assert storage._has_allowed_content(".pdf", b"  %PDF-1.7")
    assert not storage._has_allowed_content(".pdf", b"not pdf")
    assert not storage._has_allowed_content(".docx", b"broken")
    assert not storage._has_allowed_content(".txt", b"text")

    docx = io.BytesIO()
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("word/document.xml", "document")
    assert storage._has_allowed_content(".docx", docx.getvalue())

    monkeypatch.setattr(storage.settings, "UPLOAD_DIR", str(tmp_path))
    inside = tmp_path / "inside.pdf"
    inside.write_bytes(b"x")
    storage.delete_uploaded_file(str(inside))
    assert not inside.exists()
    outside = tmp_path.parent / f"outside-{uuid.uuid4().hex}.pdf"
    outside.write_bytes(b"x")
    storage.delete_uploaded_file(str(outside))
    assert outside.exists()
    outside.unlink()
    storage.delete_uploaded_file(None)
    storage.delete_uploaded_file(str(tmp_path))


@pytest.mark.asyncio
async def test_save_upload_file_validates_size_and_signature(tmp_path, monkeypatch):
    monkeypatch.setattr(storage.settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(storage.settings, "MAX_FILE_SIZE", 12)
    too_large = UploadFile(filename="cv.pdf", file=io.BytesIO(b"%PDF" + b"x" * 20))
    with pytest.raises(HTTPException) as exc:
        await storage.save_upload_file(too_large)
    assert exc.value.status_code == 400

    invalid = UploadFile(filename="cv.pdf", file=io.BytesIO(b"hello"))
    with pytest.raises(HTTPException, match="文件内容"):
        await storage.save_upload_file(invalid)

    monkeypatch.setattr(storage.settings, "MAX_FILE_SIZE", 100)
    valid = UploadFile(filename="cv.pdf", file=io.BytesIO(b"%PDF-1.7 test"))
    path = Path(await storage.save_upload_file(valid))
    assert path.parent == tmp_path
    assert path.suffix == ".pdf"
    assert path.read_bytes().startswith(b"%PDF")


def test_resume_parser_dispatch_and_extractors(monkeypatch):
    original_pdf = ResumeParser.parse_pdf
    original_docx = ResumeParser.parse_docx
    monkeypatch.setattr(ResumeParser, "parse_pdf", staticmethod(lambda path: f"pdf:{path}"))
    monkeypatch.setattr(ResumeParser, "parse_docx", staticmethod(lambda path: f"docx:{path}"))
    assert ResumeParser.parse("A.PDF") == "pdf:A.PDF"
    assert ResumeParser.parse("a.docx") == "docx:a.docx"
    assert ResumeParser.parse("a.doc") == "docx:a.doc"
    with pytest.raises(ValueError, match="不支持"):
        ResumeParser.parse("a.txt")

    monkeypatch.setattr(ResumeParser, "parse_pdf", original_pdf)
    monkeypatch.setattr(ResumeParser, "parse_docx", original_docx)

    fake_fitz = types.ModuleType("fitz")

    class FakeDoc:
        def __enter__(self):
            return [SimpleNamespace(get_text=lambda: " first "), SimpleNamespace(get_text=lambda: "second")]

        def __exit__(self, *_):
            return False

    fake_fitz.open = lambda _: FakeDoc()
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)
    assert ResumeParser.parse_pdf("fake.pdf") == "first second"

    fake_docx = types.ModuleType("docx")
    fake_docx.Document = lambda _: SimpleNamespace(
        paragraphs=[SimpleNamespace(text=" A "), SimpleNamespace(text=""), SimpleNamespace(text="B")]
    )
    monkeypatch.setitem(sys.modules, "docx", fake_docx)
    assert ResumeParser.parse_docx("fake.docx") == "A \nB"


def test_embedding_hash_remote_fallback_status_and_probe(monkeypatch):
    settings = embedding_settings()
    monkeypatch.setattr(emb, "_settings", lambda: settings)
    assert emb._normalize([0.0, 0.0]) == [0.0, 0.0]
    vector = emb._hash_embedding("Python FastAPI", 8)
    assert len(vector) == 8
    assert math.isclose(sum(v * v for v in vector), 1.0)
    assert len(emb._hash_embedding("", 8)) == 8
    with pytest.raises(emb.EmbeddingError, match="mismatch"):
        emb._validate_vectors([[1.0]], 2)
    assert emb._embedding_url("http://host/v1") == "http://host/v1/embeddings"
    assert emb._embedding_url("http://host/embeddings/") == "http://host/embeddings"

    vectors = emb.embed_texts(["a", "b"])
    assert len(vectors) == 2 and all(len(item) == 8 for item in vectors)
    assert len(emb.embed_query("q")) == 8
    status = emb.embedding_status()
    assert status["provider"] == "hash"
    assert status["last_call"]["batch_size"] == 1
    probe = emb.embedding_probe()
    assert probe["ok"] and probe["actual_vector_size"] == 8

    missing_remote = embedding_settings(EMBEDDING_PROVIDER="remote")
    monkeypatch.setattr(emb, "_settings", lambda: missing_remote)
    with pytest.raises(emb.EmbeddingError, match="BASE_URL"):
        emb._embed_remote(["a"])

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"embedding": [1.0] * 8}]}

    remote = embedding_settings(
        EMBEDDING_PROVIDER="remote", EMBEDDING_BASE_URL="http://embed", EMBEDDING_API_KEY="secret"
    )
    monkeypatch.setattr(emb, "_settings", lambda: remote)
    post = MagicMock(return_value=Response())
    monkeypatch.setattr(emb.httpx, "post", post)
    assert emb._embed_remote(["a"]) == [[1.0] * 8]
    assert post.call_args.kwargs["headers"]["authorization"] == "Bearer secret"

    class InvalidResponse(Response):
        def json(self):
            return {"data": "bad"}

    post.return_value = InvalidResponse()
    with pytest.raises(emb.EmbeddingError, match="data list"):
        emb._embed_remote(["a"])

    class MismatchResponse(Response):
        def json(self):
            return {"data": [{"embedding": [1.0]}]}

    post.return_value = MismatchResponse()
    with pytest.raises(emb.EmbeddingError, match="invalid vectors"):
        emb._embed_remote(["a", "b"])

    fallback = embedding_settings(EMBEDDING_PROVIDER="unknown", EMBEDDING_ALLOW_FALLBACK=True)
    monkeypatch.setattr(emb, "_settings", lambda: fallback)
    assert len(emb.embed_texts(["fallback"])[0]) == 8
    assert emb.embedding_status()["last_call"]["fallback_used"] is True

    strict = embedding_settings(EMBEDDING_PROVIDER="unknown")
    monkeypatch.setattr(emb, "_settings", lambda: strict)
    with pytest.raises(emb.EmbeddingError, match="Unsupported"):
        emb.embed_texts(["x"])
    monkeypatch.setattr(emb, "embed_query", lambda _: (_ for _ in ()).throw(RuntimeError("offline")))
    failed_probe = emb.embedding_probe()
    assert not failed_probe["ok"] and "offline" in failed_probe["failure_reason"]


def test_embedding_local_model_cache(monkeypatch):
    sentinel = SimpleNamespace(encode=lambda texts: [[1.0] for _ in texts])
    monkeypatch.setattr(emb, "_local_model", None)
    monkeypatch.setattr(emb, "_BgeM3TransformersModel", lambda: sentinel)
    assert emb._get_local_model() is sentinel
    assert emb._get_local_model() is sentinel


def test_rerank_remote_order_fallback_and_status(monkeypatch):
    disabled = rerank_settings()
    monkeypatch.setattr(rr, "_settings", lambda: disabled)
    assert not rr.rerank_enabled()
    order, meta = rr.rerank_documents("q", ["a", "b"])
    assert order == [0, 1] and not meta["enabled"]
    assert rr.rerank_documents("q", [])[0] == []
    assert rr._rerank_url("http://host/v1") == "http://host/v1/rerank"
    assert rr._rerank_url("http://host/rerank/") == "http://host/rerank"

    missing = rerank_settings(RERANK_PROVIDER="remote")
    monkeypatch.setattr(rr, "_settings", lambda: missing)
    with pytest.raises(rr.RerankError, match="BASE_URL"):
        rr._remote_scores("q", ["a"])

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": [{"relevance_score": 0.2}, {"score": 0.9}]}

    remote = rerank_settings(RERANK_PROVIDER="remote", RERANK_BASE_URL="http://rank", RERANK_API_KEY="secret")
    monkeypatch.setattr(rr, "_settings", lambda: remote)
    post = MagicMock(return_value=Response())
    monkeypatch.setattr(rr.httpx, "post", post)
    assert rr._remote_scores("q", ["a", "b"]) == [0.2, 0.9]
    order, meta = rr.rerank_documents("q", ["a", "b"])
    assert order == [1, 0] and meta["scores"] == [0.9, 0.2]
    assert rr.rerank_status()["base_url_configured"]
    assert "query" not in rr._last_observation

    class AltResponse(Response):
        def json(self):
            return {"data": [0.4, 0.1]}

    post.return_value = AltResponse()
    assert rr._remote_scores("q", ["a", "b"]) == [0.4, 0.1]

    class BadResponse(Response):
        def json(self):
            return {"results": "bad"}

    post.return_value = BadResponse()
    with pytest.raises(rr.RerankError, match="results list"):
        rr._remote_scores("q", ["a"])

    class ShortResponse(Response):
        def json(self):
            return {"results": [0.1]}

    post.return_value = ShortResponse()
    with pytest.raises(rr.RerankError, match="mismatched"):
        rr._remote_scores("q", ["a", "b"])

    fallback = rerank_settings(RERANK_PROVIDER="unsupported", RERANK_ALLOW_FALLBACK=True)
    monkeypatch.setattr(rr, "_settings", lambda: fallback)
    order, meta = rr.rerank_documents("q", ["a"])
    assert order == [0] and meta["fallback_used"] and "Unsupported" in meta["failure_reason"]

    strict = rerank_settings(RERANK_PROVIDER="unsupported")
    monkeypatch.setattr(rr, "_settings", lambda: strict)
    with pytest.raises(rr.RerankError):
        rr.rerank_documents("q", ["a"])


def test_rerank_local_model_cache_and_local_provider(monkeypatch):
    fake = SimpleNamespace(score=lambda q, docs: [float(i) for i, _ in enumerate(docs)])
    monkeypatch.setattr(rr, "_local_reranker", None)
    monkeypatch.setattr(rr, "_BgeReranker", lambda: fake)
    assert rr._get_local_reranker() is fake
    settings = rerank_settings(RERANK_PROVIDER="bge")
    monkeypatch.setattr(rr, "_settings", lambda: settings)
    order, meta = rr.rerank_documents("q", ["a", "b"])
    assert order == [1, 0] and meta["provider"] == "bge_reranker"


def test_resume_index_pure_contracts(monkeypatch):
    settings = SimpleNamespace(RESUME_CHUNK_SIZE=220, RESUME_CHUNK_OVERLAP=20, QDRANT_RESUME_COLLECTION="resume-v1")
    monkeypatch.setattr(ri, "_settings", lambda: settings)
    terms = ri.normalize_terms("Python、FastAPI / Redis; python PostgreSQL")
    assert terms[0] == "python" and len(terms) == len(set(terms))
    assert ri.extract_keywords("FastAPI and PostgreSQL")
    assert "b: 2" in ri._as_text({"b": 2, "a": 1})
    assert ri._as_text(["a", {"x": "b"}])
    assert ri._as_text(None) == ""
    assert ri._dedupe(["A", "a", "B"]) == ["A", "B"]
    assert ri._token_estimate("12345678") >= 1
    assert ri.recursive_chunk_text("") == []
    long_text = ("第一段 Python FastAPI PostgreSQL。" * 30) + "\n\n" + ("第二段 Redis Qdrant。" * 30)
    chunks = ri.recursive_chunk_text(long_text, chunk_size=220, overlap=20)
    assert len(chunks) > 2 and all(len(item) <= 240 for item in chunks)

    resume = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        title="后端简历",
        original_text="raw",
        parsed_data={
            "skills": ["Python", "FastAPI"],
            "education": [{"school": "某大学", "major": "CS"}],
            "experience": [{"company": "某科技", "role": "后端", "description": "负责服务"}],
            "projects": [{"name": "Agent", "description": "RAG Qdrant 检索系统"}],
            "summary": "工程质量和交付能力",
        },
    )
    sources = ri._structured_sources(resume)
    assert {item[0] for item in sources} == {"skills", "education", "experience", "project", "summary"}
    payloads = ri.build_resume_chunk_payloads(resume)
    assert payloads and all(len(item["source_hash"]) == 64 for item in payloads)
    assert ri._resume_collection_name() == "resume-v1"

    fallback = SimpleNamespace(**{**resume.__dict__, "parsed_data": None, "original_text": "足够长的原始简历正文"})
    assert ri._structured_sources(fallback)[0][0] == "full_text"
    chunk = SimpleNamespace(
        id=uuid.uuid4(),
        resume_id=resume.id,
        user_id=resume.user_id,
        organization_id=resume.organization_id,
        section="project",
        item_title="Agent",
        chunk_index=1,
        keywords=["agent", "python"],
        content="RAG Python FastAPI evidence",
        created_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
    )
    vector_payload = ri._vector_payload(chunk)
    assert vector_payload["project_name"] == "Agent" and vector_payload["doc_type"] == "resume"
    assert ri._score_resume_chunk(["python", "fastapi"], chunk) > 0


def test_company_profile_normalization_and_prompt_contracts():
    assert cp.normalize_company_name("Alibaba 集团") == "阿里巴巴"
    assert cp.normalize_company_name("某某科技有限公司") == "某某科技"
    assert cp.normalize_position_name("Backend Intern") == "后端开发实习"
    rounds = cp.normalize_rounds("一面 / 系统设计 / 自定义面")
    assert {item["round_type"] for item in rounds} >= {"technical_first", "system_design", "自定义面"}
    assert cp.canonicalize_question("Q1：请介绍 Redis？") == "请介绍 Redis"
    assert cp._same_question("介绍一下 Redis", "介绍一下redis")
    topics = cp.detect_technical_topics("FastAPI PostgreSQL Redis Docker 可观测性")
    topic_keys = {item["topic_key"] for item in topics}
    assert {"database", "cache_queue", "deployment", "observability"}.issubset(topic_keys)
    assert cp.profile_confidence(0) == "low"
    assert cp.profile_confidence(3) == "medium"
    assert cp.profile_confidence(8) == "high"
    assert cp.infer_target_from_jd("company: Alibaba\nposition: backend engineer") == ("Alibaba", "backend engineer")

    profile = SimpleNamespace(
        id=uuid.uuid4(),
        company_name="Tencent",
        position_name="backend",
        scope="public",
        interview_count=12,
        profile_version=1,
        common_rounds=[{"round_type": "technical_first", "name": "first round", "source_count": 3}],
        frequent_questions=[
            {
                "canonical_question": "How does Redis stay consistent?",
                "round_type": "technical_first",
                "difficulty": "medium",
                "source_count": 3,
            }
        ],
        technical_topics=[{"name": "database", "source_count": 4}],
        generated_at=datetime.now(timezone.utc),
    )
    snapshot = cp.company_profile_snapshot(profile)
    assert snapshot["matched_company"] == "Tencent" and snapshot["source_count"] == 12
    prompt = cp.company_profile_prompt_context(snapshot, "technical_first")
    assert "Redis" in prompt and "database" in prompt
    assert cp.company_profile_prompt_context(None, "technical_first") == ""


def test_version_compare_and_original_guard():
    base = SimpleNamespace(
        id=uuid.uuid4(),
        version_number=1,
        title="原始",
        version_type="original",
        ats_report={"total_score": 60},
        change_details=[1],
    )
    target = SimpleNamespace(
        id=uuid.uuid4(),
        version_number=2,
        title="JD版",
        version_type="jd",
        ats_report={"total_score": 78.5},
        change_details=[1, 2, 3],
    )
    result = build_version_compare(base, target)
    assert result["score_delta"] == 18.5 and result["change_count_delta"] == 2


@pytest.mark.asyncio
async def test_ensure_original_version_invalid_existing_and_create(monkeypatch):
    db = SimpleNamespace(scalar=AsyncMock(return_value=None))
    invalid = SimpleNamespace(parsed_data=None)
    assert await ensure_original_version(db, invalid) is None

    existing = object()
    db.scalar.return_value = existing
    resume = SimpleNamespace(id=uuid.uuid4(), title="简历", parsed_data={"name": "张三"})
    assert await ensure_original_version(db, resume) is existing

    db.scalar.return_value = None
    created = object()
    create = AsyncMock(return_value=created)
    monkeypatch.setattr("app.services.resume_versions.create_resume_version", create)
    assert await ensure_original_version(db, resume) is created
    assert create.await_args.kwargs["version_type"] == "original"
