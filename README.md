# 面试简历 Agent / Agent Platform v2

面试简历 Agent 是一个正在向 **Harness + MCP + Skills + 多 Agent** 架构演进的求职训练平台。当前代码仍以 FastAPI 模块化单体和 React 前端为核心，已经完成 Phase 1A 产品表面收缩，并开始建设 Phase 1B 历史数据契约审计。

> 当前边界必须明确：项目已实现隔离的 **shadow runtime**（5 个 Agent、4 个 Skill、2 个只读 MCP-compatible Tool）以及 PostgreSQL Run Store 代码、事务幂等、持久化 Checkpoint/Trace、执行租约和取消竞争处理。本地默认仍使用 memory Store；真实 PostgreSQL 多实例/恢复演练、durable worker、生产 Agent API 和网络 MCP Server 尚未完成，因此不能描述为生产 Harness/MCP 已完成。

## 当前产品能力

已保留并持续维护：

- 简历上传、解析、结构化编辑、版本和导出；
- 基于 JD 的匹配分析和定向改写；
- 岗位申请跟踪；
- 模拟面试、动态问题、回答评分和报告导出；
- 训练计划、题目练习和训练画像；
- RAG 知识库、任务队列、审计、账号导出与账号删除；
- health、status、release check、alerts、backup 等受控运维能力。

Phase 1A 已退役的产品表面：

- 支付、订单、套餐、价格、升级和商业 entitlement；
- 组织/公司管理 UI 与公开 API；
- 公司画像 CRUD UI 与公开 API；
- 运营后台 UI；
- 面向用户的质量反馈 UI/API。

当前 SQLAlchemy 元数据共 29 张表：26 张历史业务表继续保留 personal organization 兼容数据，另有 3 张 Agent Runtime 表。Phase 1B 尚未执行历史业务删表、删列或破坏性迁移。

## 当前阶段

| 阶段 | 状态 |
|---|---|
| Phase 0：基线与质量门 | 已合并 `main`（`11bf353`） |
| Phase 1A：产品表面退役 | 已合并 `main`（`11bf353`） |
| Phase 1B：历史数据契约 | 只读审计基础已实现；真实数据迁移未开始 |
| Phase 2：Agent Harness | PostgreSQL Store、事务幂等、Checkpoint/Trace、执行租约、取消竞争和用户隔离的 Run Inspector API 已实现；Inspector UI、durable worker、kill/restart、多实例实测和生产 API 未完成 |
| Phase 3：MCP + Skills | 4 个 Skill、2 个只读 MCP-compatible Tool；注册表和事实安全门已激活 |
| Phase 4：多 Agent | 5 个 Agent 的 Supervisor/Handoff 隔离闭环已实现，尚未替换生产主链路 |
| Phase 5：证据化简历改写 | Evidence Hash + source-exact 重排已实现；人工盲评和 120 条基准集尚未完成 |

详细计划见 [`docs/AGENT_PLATFORM_DEVELOPMENT_SPEC.md`](docs/AGENT_PLATFORM_DEVELOPMENT_SPEC.md)。

## 技术栈

### 后端

- Python 3.12、FastAPI、Pydantic Settings；
- SQLAlchemy Async、Alembic、SQLite/PostgreSQL；
- Redis/RQ 可选任务队列；
- Qdrant/关键词检索、Embedding 和 Reranker 适配；
- 多 LLM Provider 适配层；
- pytest、coverage、Ruff、mypy、pip-audit。

### 前端

- React 18、TypeScript、Vite；
- TailwindCSS、Zustand、Axios；
- Vitest、ESLint、Playwright。

## 项目结构

```text
.
├── backend/                 # FastAPI、数据模型、服务、迁移和测试
├── frontend/                # React 前端、单元测试和 E2E
├── quality/                 # OpenAPI、Agent、Skills 冻结/规划注册表
├── scripts/                 # 统一质量门、契约和密钥校验
├── deploy/                  # 部署环境模板
├── artifacts/               # 本地质量证据；默认不应提交生成物
└── docs/                    # 架构、质量、评测、ADR 和迁移文档
```

## 本地开发

### 后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 前端

```powershell
cd frontend
npm ci
npm run dev
```

默认前端地址为 `http://127.0.0.1:5173`，后端地址为 `http://127.0.0.1:8000`。

## 统一质量门

```powershell
# 完整 CI 阻断门
backend\.venv-codex\Scripts\python.exe scripts\run_quality_gate.py `
  --profile all `
  --mode ci

# 发布候选门；后端总行覆盖率必须达到 85%
backend\.venv-codex\Scripts\python.exe scripts\run_quality_gate.py `
  --profile all `
  --mode release
```

CI 的 64% 是存量 ratchet，不是发布标准。2026-08-27 最新后端 Release Gate 已以 `86.15%` 总行覆盖率通过，前端、契约、安全和 3 条 Chromium E2E 也已通过；不得降低阈值、删除失败测试或把未运行检查写成通过。

质量标准和当前实测值分别见：

- [`docs/QUALITY_GATE_STANDARD.md`](docs/QUALITY_GATE_STANDARD.md)
- [`docs/BASELINE_INVENTORY.md`](docs/BASELINE_INVENTORY.md)

## Phase 1B 只读数据审计

```powershell
cd backend
.\.venv-codex\Scripts\python.exe scripts\audit_phase1b_data_contract.py `
  --database-url "postgresql+asyncpg://<readonly-user>@<host>/<database>" `
  --report artifacts\data-contract\phase1b-postgresql-audit.json
```

审计只读取 row count、外键和归属关系，不输出用户正文或支付载荷。发现孤儿记录、跨用户归属、共享组织或公司画像 owner 歧义时默认返回非零退出码。执行规范见 [`docs/PHASE1B_DATA_CONTRACT_AUDIT.md`](docs/PHASE1B_DATA_CONTRACT_AUDIT.md)。

## Docker 部署

项目提供 PostgreSQL、Redis、Qdrant、后端、RQ worker 和前端 Nginx 的 Docker Compose 配置：

```powershell
Copy-Item deploy/compose.env.example deploy/compose.env
Copy-Item backend/.env.production.example backend/.env.production
docker compose --env-file deploy/compose.env build
docker compose --env-file deploy/compose.env up -d
```

生产部署前必须替换密钥、模型 Key、域名和告警配置，并通过 release 质量门、数据库备份恢复演练和安全评审。详见 [`docs/DOCKER_DEPLOYMENT.md`](docs/DOCKER_DEPLOYMENT.md)。

## 文档入口

- [`docs/README.md`](docs/README.md)：权威文档索引；
- [`docs/AGENT_PLATFORM_DEVELOPMENT_SPEC.md`](docs/AGENT_PLATFORM_DEVELOPMENT_SPEC.md)：企业级开发规范和阶段计划；
- [`docs/RESUME_REWRITE_EVALUATION.md`](docs/RESUME_REWRITE_EVALUATION.md)：真实有效的简历改写评测标准；
- [`docs/adr/0002-product-surface-retirement.md`](docs/adr/0002-product-surface-retirement.md)：Phase 1A 退役决策。

## Git 与敏感信息

不要提交真实 `.env`、数据库、日志、依赖目录、构建产物、覆盖率、Playwright 报告、质量 Artifact 或用户数据。提交前至少执行：

```powershell
git diff --check
git status --short --branch
```

交付状态以受保护分支上的 Pull Request、GitHub Actions 结果和最终合并提交为准；本地报告不得替代 commit 级 CI 证据。
