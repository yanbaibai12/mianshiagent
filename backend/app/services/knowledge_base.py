import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models import KnowledgeChunk, KnowledgeDocument
from app.services.rerank_service import rerank_documents, rerank_enabled
from app.services.vector_store import search_vector_knowledge, sync_knowledge_to_vector_store

DEFAULT_KNOWLEDGE = [
    {
        "title": "技术岗项目面试评分标准",
        "category": "interview_rubric",
        "tags": ["技术岗", "项目深挖", "STAR", "评分"],
        "chunks": [
            {
                "keywords": ["STAR", "技术深度", "项目背景", "个人贡献", "量化结果"],
                "content": "技术项目回答应覆盖背景、目标、个人职责、关键方案、技术取舍、困难定位、结果指标和复盘。评分重点不是技术名词数量，而是候选人能否说明为什么这样设计、如何验证效果、本人贡献是否清楚。",
            },
            {
                "keywords": ["追问", "方案取舍", "架构设计", "风险"],
                "content": "项目追问常围绕方案取舍、边界条件、稳定性、性能、成本和风险展开。优秀回答会给出备选方案比较、上线验证方式、故障兜底和后续优化方向。",
            },
        ],
    },
    {
        "title": "后端岗位核心能力模型",
        "category": "job_knowledge",
        "tags": ["后端", "Python", "Java", "数据库", "Redis", "接口"],
        "chunks": [
            {
                "keywords": ["FastAPI", "接口设计", "鉴权", "限流", "日志"],
                "content": "后端岗位常考接口设计、认证鉴权、参数校验、异常处理、日志追踪、限流降级、幂等性和可观测性。回答时要结合请求链路说明输入、处理、存储、返回和故障处理。",
            },
            {
                "keywords": ["SQL", "索引", "PostgreSQL", "MySQL", "查询优化"],
                "content": "数据库优化回答应包含慢查询定位、执行计划、索引设计、分页策略、事务边界和数据一致性。避免只说加索引，要说明为什么该索引能命中查询条件。",
            },
            {
                "keywords": ["Redis", "缓存", "缓存穿透", "缓存雪崩", "缓存击穿"],
                "content": "Redis 缓存类问题可从缓存模式、过期策略、一致性、穿透/击穿/雪崩防护、热点 Key 和监控告警展开。项目回答要说明命中率、延迟、数据一致性取舍。",
            },
        ],
    },
    {
        "title": "前端岗位核心能力模型",
        "category": "job_knowledge",
        "tags": ["前端", "React", "TypeScript", "性能", "工程化"],
        "chunks": [
            {
                "keywords": ["React", "状态管理", "组件设计", "性能优化"],
                "content": "前端项目面试常追问组件拆分、状态管理、渲染性能、接口错误处理、权限路由和用户体验。回答要说明为什么这样拆分组件、如何降低重复渲染、如何保证复杂表单可维护。",
            },
            {
                "keywords": ["工程化", "TypeScript", "构建", "质量"],
                "content": "前端工程化重点包括 TypeScript 类型约束、构建优化、代码规范、自动化测试、错误监控和发布回滚。优秀回答会把工程措施和业务稳定性联系起来。",
            },
        ],
    },
    {
        "title": "产品岗位核心能力模型",
        "category": "job_knowledge",
        "tags": ["产品", "用户调研", "需求分析", "数据分析", "A/B"],
        "chunks": [
            {
                "keywords": ["需求分析", "用户调研", "PRD", "优先级"],
                "content": "产品岗简历和面试要突出用户问题、需求来源、优先级判断、方案设计、跨团队推进和结果指标。回答应避免只描述功能列表，要说明判断依据和取舍逻辑。",
            },
            {
                "keywords": ["数据分析", "转化率", "留存", "A/B", "指标"],
                "content": "产品数据回答要明确北极星指标、过程指标、实验设计、样本口径和复盘结论。优秀表达会说明数据如何影响决策，而不是只罗列 DAU、转化率等指标。",
            },
        ],
    },
    {
        "title": "运营岗位核心能力模型",
        "category": "job_knowledge",
        "tags": ["运营", "增长", "活动", "内容", "转化"],
        "chunks": [
            {
                "keywords": ["活动运营", "增长", "转化率", "ROI"],
                "content": "运营岗应突出目标人群、活动机制、渠道策略、执行节奏、数据复盘和 ROI。面试回答要体现从目标到策略再到结果的闭环，而不是只描述执行动作。",
            },
            {
                "keywords": ["内容运营", "用户分层", "留存"],
                "content": "内容和用户运营要说明用户分层、触达策略、内容定位、转化链路和留存复盘。优秀回答会给出具体指标和下次迭代策略。",
            },
        ],
    },
    {
        "title": "简历表达优化规则",
        "category": "resume_writing",
        "tags": ["简历", "STAR", "量化", "真实性"],
        "chunks": [
            {
                "keywords": ["简历优化", "STAR", "量化成果", "真实性"],
                "content": "简历优化只允许重组表达、突出重点和补充用户已提供的信息，不得虚构经历、技能或数据。经历描述优先使用 STAR：背景/目标、任务、行动、结果，每条尽量落到个人贡献和可验证结果。",
            },
            {
                "keywords": ["JD匹配", "关键词", "薄弱项"],
                "content": "JD 定向优化应先提取职责、必备技能、加分项和关键词，再判断简历已有证据。匹配表达应把已有经历向岗位语言靠拢，但不能把未出现的技能包装成已掌握。",
            },
        ],
    },
    {
        "title": "面试报告改进建议规则",
        "category": "reporting",
        "tags": ["报告", "薄弱点", "复习建议"],
        "chunks": [
            {
                "keywords": ["完整性", "逻辑", "一致性", "精炼", "深度"],
                "content": "面试报告要围绕完整性、逻辑清晰度、与简历一致性、表达精炼度、技术/业务深度五个维度归因。建议必须具体到可练习动作，例如补充指标、准备方案取舍、复盘故障定位。",
            },
            {
                "keywords": ["复习方向", "项目复盘", "表达训练"],
                "content": "复习建议应按优先级排序：先补项目事实和个人贡献，再补方案取舍和指标，最后训练 60 秒精简表达。每个建议都应能转化为下一次练习题。",
            },
        ],
    },
]


@dataclass
class KnowledgeSnippet:
    document_id: str
    chunk_id: str
    title: str
    category: str
    source: str
    tags: list[str]
    keywords: list[str]
    metadata: dict[str, Any]
    content: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        public_metadata = {
            key: self.metadata.get(key)
            for key in ["question_id", "section", "difficulty", "roles", "skills", "source_version", "slice_index", "slice_count"]
            if self.metadata.get(key) is not None
        }
        return {
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "title": self.title,
            "category": self.category,
            "source": self.source,
            "tags": self.tags,
            "keywords": self.keywords,
            "metadata": public_metadata,
            "content": self.content,
            "score": round(self.score, 3),
        }


def _normalize_terms(text: str) -> list[str]:
    text = (text or "").lower()
    terms = re.findall(r"[a-zA-Z][a-zA-Z0-9+#./-]{1,}|[\u4e00-\u9fa5]{2,8}", text)
    stop_words = {"岗位要求", "项目经历", "工作经历", "负责", "参与", "以及", "通过", "进行", "相关", "能力"}
    technical_terms = [
        "agent",
        "rag",
        "rrf",
        "bm25",
        "rerank",
        "qdrant",
        "bge-m3",
        "bge",
        "fastapi",
        "redis",
        "postgresql",
        "mysql",
        "react",
        "function calling",
        "tool calling",
        "prompt injection",
        "幂等",
        "项目",
        "实习",
        "八股",
        "切片",
        "召回",
        "重排",
        "向量",
        "索引",
        "队列",
        "重试",
        "日志",
        "脱敏",
        "权限",
        "评测",
        "套话",
    ]
    result = []
    seen = set()
    for term in [*terms, *[term for term in technical_terms if term in text]]:
        if term in stop_words:
            continue
        if term not in seen:
            seen.add(term)
            result.append(term)
    return result[:80]


def _token_estimate(content: str) -> int:
    return max(1, len(content) // 2)


async def seed_builtin_knowledge(db: AsyncSession) -> None:
    for item in DEFAULT_KNOWLEDGE:
        existing_result = await db.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.title == item["title"])
        )
        existing = existing_result.scalar_one_or_none()
        if existing:
            continue

        document = KnowledgeDocument(
            title=item["title"],
            category=item["category"],
            source="builtin",
            tags=item["tags"],
            is_builtin=True,
            is_active=True,
        )
        for index, chunk in enumerate(item["chunks"], 1):
            document.chunks.append(
                KnowledgeChunk(
                    sequence=index,
                    content=chunk["content"],
                    keywords=chunk["keywords"],
                    token_estimate=_token_estimate(chunk["content"]),
                )
            )
        db.add(document)
    await db.commit()
    await sync_knowledge_to_vector_store(db, respect_startup_flag=True)


def _score_chunk(
    query_terms: list[str],
    document: KnowledgeDocument,
    chunk: KnowledgeChunk,
    categories: set[str],
) -> float:
    haystack = " ".join(
        [
            document.title,
            document.category,
            " ".join(document.tags or []),
            " ".join(chunk.keywords or []),
            compact_json(getattr(chunk, "chunk_metadata", {}) or {}, 1200),
            chunk.content,
        ]
    ).lower()
    score = 0.0
    for term in query_terms:
        if term in haystack:
            score += 1.0
            if term in " ".join(chunk.keywords or []).lower():
                score += 1.5
            if term in document.title.lower():
                score += 0.5

    if categories and document.category in categories:
        score += 2.0

    return score


async def _retrieve_keyword_knowledge(
    db: AsyncSession,
    query_terms: list[str],
    category_set: set[str],
    limit: int = 5,
) -> list[KnowledgeSnippet]:
    result = await db.execute(
        select(KnowledgeDocument)
        .options(selectinload(KnowledgeDocument.chunks))
        .where(KnowledgeDocument.is_active.is_(True))
    )
    documents = result.scalars().all()

    snippets: list[KnowledgeSnippet] = []
    for document in documents:
        for chunk in document.chunks:
            score = _score_chunk(query_terms, document, chunk, category_set)
            if score <= 0 and not category_set:
                continue
            if score <= 0 and document.category not in category_set:
                continue
            snippets.append(
                KnowledgeSnippet(
                    document_id=str(document.id),
                    chunk_id=str(chunk.id),
                    title=document.title,
                    category=document.category,
                    source=document.source or "builtin",
                    tags=document.tags or [],
                    keywords=chunk.keywords or [],
                    metadata=chunk.chunk_metadata or {},
                    content=chunk.content,
                    score=score,
                )
            )

    snippets.sort(key=lambda item: item.score, reverse=True)
    return snippets[:limit]


def _vector_payload_to_snippet(payload: dict[str, Any]) -> KnowledgeSnippet:
    metadata = dict(payload.get("metadata") or {})
    for key in ["question_id", "section", "difficulty", "roles", "skills", "source_version", "slice_index", "slice_count"]:
        if key not in metadata and payload.get(key) is not None:
            metadata[key] = payload.get(key)
    return KnowledgeSnippet(
        document_id=str(payload.get("document_id") or ""),
        chunk_id=str(payload.get("chunk_id") or ""),
        title=str(payload.get("title") or ""),
        category=str(payload.get("category") or ""),
        source=str(payload.get("source") or "vector"),
        tags=list(payload.get("tags") or []),
        keywords=list(payload.get("keywords") or []),
        metadata=metadata,
        content=str(payload.get("content") or ""),
        score=float(payload.get("score") or 0),
    )


def _merge_ranked_snippets(
    vector_snippets: list[KnowledgeSnippet],
    keyword_snippets: list[KnowledgeSnippet],
    limit: int,
) -> list[KnowledgeSnippet]:
    if not vector_snippets:
        return keyword_snippets[:limit]
    if not keyword_snippets:
        return vector_snippets[:limit]

    by_key: dict[str, KnowledgeSnippet] = {}
    combined_scores: dict[str, float] = {}
    for weight, snippets in [(1.0, vector_snippets), (0.85, keyword_snippets)]:
        for rank, snippet in enumerate(snippets, 1):
            key = snippet.chunk_id or f"{snippet.document_id}:{snippet.title}:{rank}"
            by_key.setdefault(key, snippet)
            combined_scores[key] = combined_scores.get(key, 0.0) + weight / (60 + rank)

    merged = list(by_key.items())
    merged.sort(key=lambda item: combined_scores[item[0]], reverse=True)
    result: list[KnowledgeSnippet] = []
    for key, snippet in merged[:limit]:
        snippet.score = round(combined_scores[key] * 1000, 3)
        result.append(snippet)
    return result


async def retrieve_knowledge(
    db: AsyncSession,
    query: str,
    *,
    categories: list[str] | None = None,
    limit: int = 5,
) -> list[KnowledgeSnippet]:
    query_terms = _normalize_terms(query)
    category_set = set(categories or [])
    keyword_snippets = await _retrieve_keyword_knowledge(db, query_terms, category_set, limit=max(limit * 2, limit))
    vector_payloads = await search_vector_knowledge(query, categories=categories, limit=max(limit * 2, limit))
    vector_snippets = [_vector_payload_to_snippet(payload) for payload in vector_payloads]
    settings = get_settings()
    rerank_candidate_limit = max(limit, settings.RERANK_TOP_K)
    merged = _merge_ranked_snippets(vector_snippets, keyword_snippets, max(limit * 3, rerank_candidate_limit))
    if not rerank_enabled() or len(merged) <= 1:
        return merged[:limit]
    candidates = merged[:rerank_candidate_limit]
    documents = [f"{snippet.title}\n{snippet.category}\n{snippet.content}" for snippet in candidates]
    order, observation = await asyncio.to_thread(rerank_documents, query, documents)
    if observation.get("fallback_used"):
        return merged[:limit]
    reranked = [candidates[index] for index in order if index < len(candidates)]
    for index, snippet in enumerate(reranked, 1):
        score_boost = max(0, len(reranked) - index + 1) / max(1, len(reranked))
        snippet.score = round(snippet.score + score_boost, 3)
    return reranked[:limit]


def build_rag_context(snippets: list[KnowledgeSnippet]) -> str:
    if not snippets:
        return "未检索到可用知识片段。"

    lines = [
        "检索增强上下文（仅作为岗位知识、评分标准和表达规则参考；不得虚构用户未提供的经历、技能或数据）："
    ]
    for index, snippet in enumerate(snippets, 1):
        keywords = "、".join(snippet.keywords[:6])
        metadata_parts = []
        if snippet.metadata.get("question_id"):
            metadata_parts.append(f"题卡ID：{snippet.metadata['question_id']}")
        if snippet.metadata.get("section"):
            metadata_parts.append(f"方向：{snippet.metadata['section']}")
        if snippet.metadata.get("difficulty"):
            metadata_parts.append(f"难度：{snippet.metadata['difficulty']}")
        if snippet.metadata.get("skills"):
            metadata_parts.append(f"技能：{'、'.join(list(snippet.metadata['skills'])[:6])}")
        metadata_line = f" | {'；'.join(metadata_parts)}" if metadata_parts else ""
        lines.append(
            f"{index}. [{snippet.category}] {snippet.title} | 关键词：{keywords}{metadata_line}\n{snippet.content}"
        )
    return "\n".join(lines)


def serialize_rag_references(snippets: list[KnowledgeSnippet]) -> list[dict[str, Any]]:
    return [
        {
            "title": snippet.title,
            "category": snippet.category,
            "source": snippet.source,
            "keywords": snippet.keywords[:8],
            "score": round(snippet.score, 2),
        }
        for snippet in snippets
    ]


def compact_json(data: Any, max_chars: int = 5000) -> str:
    text = json.dumps(data, ensure_ascii=False, default=str)
    return text[:max_chars]
