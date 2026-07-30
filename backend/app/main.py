from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse

from app.config import get_settings
from app.database import init_db, async_session_maker
from app.middleware import InMemoryRateLimitMiddleware, RequestMetricsMiddleware, SecurityHeadersMiddleware
from app.models import ResumeTemplate
from app.routers import account, audit, auth, resumes, templates, interviews, system, knowledge, business, organizations, payments, tasks, jobs, quality
from app.services.knowledge_base import seed_builtin_knowledge
from app.services.llm_client import LLMCallError
from app.services.release_checks import assert_release_ready

settings = get_settings()

DEFAULT_TEMPLATES = [
    {
        "id": "tech",
        "name": "技术岗模板",
        "category": "tech",
        "structure": {
            "modules": ["personal", "skills", "projects", "experience", "education", "summary"],
            "rules": [
                "技术栈放在显眼位置",
                "项目经历使用 STAR 法则",
                "量化性能指标，如 QPS、耗时、用户数",
                "突出技术难点和解决方案",
            ],
        },
        "prompt": """你正在为技术岗位优化简历。要求：
1. 模块顺序：个人信息 → 技能 → 项目经历 → 工作经历 → 教育背景 → 自我评价
2. 技术栈突出，放在技能模块前列
3. 项目经历使用 STAR 法则：背景、任务、行动、结果
4. 量化成果：QPS、响应时间、用户数、代码覆盖率等
5. 突出技术难点和架构设计
6. 语言精炼，每段不超过 3 行
7. 不得虚构经历或数据""",
    },
    {
        "id": "product",
        "name": "产品岗模板",
        "category": "product",
        "structure": {
            "modules": ["personal", "experience", "projects", "education", "skills", "summary"],
            "rules": [
                "突出用户调研、需求分析、数据驱动决策",
                "量化产品指标，如 DAU、转化率、留存率",
                "体现跨部门协作能力",
            ],
        },
        "prompt": """你正在为产品经理岗位优化简历。要求：
1. 模块顺序：个人信息 → 工作经历 → 项目经历 → 教育背景 → 技能 → 自我评价
2. 突出用户调研、需求分析、产品规划能力
3. 使用数据说话：DAU、转化率、留存率、营收等
4. 体现跨部门协作和项目管理能力
5. 语言精炼，每段不超过 3 行
6. 不得虚构经历或数据""",
    },
    {
        "id": "operation",
        "name": "运营岗模板",
        "category": "operation",
        "structure": {
            "modules": ["personal", "experience", "projects", "skills", "education", "summary"],
            "rules": [
                "突出活动策划、用户增长、内容运营经验",
                "量化运营指标，如 GMV、ROI、粉丝增长",
                "体现文案、数据分析、活动策划能力",
            ],
        },
        "prompt": """你正在为运营岗位优化简历。要求：
1. 模块顺序：个人信息 → 工作经历 → 项目经历 → 技能 → 教育背景 → 自我评价
2. 突出活动策划、用户增长、内容运营经验
3. 量化运营指标：GMV、ROI、转化率、粉丝增长等
4. 体现文案、数据分析、跨部门协作能力
5. 语言精炼，每段不超过 3 行
6. 不得虚构经历或数据""",
    },
    {
        "id": "general",
        "name": "通用模板",
        "category": "general",
        "structure": {
            "modules": ["personal", "education", "experience", "projects", "skills", "summary"],
            "rules": [
                "结构清晰，重点突出",
                "使用 STAR 法则描述经历",
                "尽量量化成果",
            ],
        },
        "prompt": """你正在使用通用模板优化简历。要求：
1. 模块顺序：个人信息 → 教育背景 → 工作经历 → 项目经历 → 技能 → 自我评价
2. 结构清晰，重点突出
3. 使用 STAR 法则描述经历
4. 尽量量化成果
5. 语言精炼，每段不超过 3 行
6. 不得虚构经历或数据""",
    },
]


async def init_templates():
    async with async_session_maker() as db:
        for tpl in DEFAULT_TEMPLATES:
            from sqlalchemy import select
            result = await db.execute(select(ResumeTemplate).where(ResumeTemplate.id == tpl["id"]))
            existing = result.scalar_one_or_none()
            if not existing:
                template = ResumeTemplate(
                    id=tpl["id"],
                    name=tpl["name"],
                    category=tpl["category"],
                    structure=tpl["structure"],
                    prompt=tpl["prompt"],
                )
                db.add(template)
        await db.commit()


async def init_knowledge():
    async with async_session_maker() as db:
        await seed_builtin_knowledge(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    assert_release_ready(settings)
    if settings.AUTO_CREATE_DB:
        await init_db()
    await init_templates()
    await init_knowledge()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description="基于 LLM 的简历优化与模拟面试系统",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if settings.ENABLE_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_DOCS else None,
)

app.add_middleware(SecurityHeadersMiddleware, settings=settings)
app.add_middleware(RequestMetricsMiddleware, settings=settings)
app.add_middleware(InMemoryRateLimitMiddleware, settings=settings)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.TRUSTED_HOSTS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(account.router)
app.include_router(audit.router)
app.include_router(organizations.router)
app.include_router(payments.router)
app.include_router(tasks.router)
app.include_router(jobs.router)
app.include_router(resumes.router)
app.include_router(templates.router)
app.include_router(interviews.router)
app.include_router(system.router)
app.include_router(knowledge.router)
app.include_router(business.router)
app.include_router(quality.router)


@app.exception_handler(LLMCallError)
async def llm_call_error_handler(request: Request, exc: LLMCallError):
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=502,
        content={
            "detail": str(exc),
            "request_id": request_id,
        },
    )


@app.get("/health")
async def health_check():
    return {"status": "ok"}
