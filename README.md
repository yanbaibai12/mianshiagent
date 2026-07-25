# 面试简历 Agent

面试简历 Agent 是一个面向求职训练场景的 AI 应用，覆盖“简历解析、简历优化、JD 定向适配、模拟面试、回答评分、报告导出、账号治理、组织协作和运营后台”的完整闭环。

项目使用 FastAPI + SQLAlchemy + Alembic 构建后端，React + Vite + TailwindCSS 构建前端，并提供本地 RAG 知识库、LLM 多供应商适配、审计日志、权益/支付、组织管理、备份、监控、灰度配置和 CI/E2E 测试等工程化能力。

## 核心能力

- 简历上传：支持粘贴文本、PDF、DOCX，后端校验文件扩展名和真实内容格式。
- 简历结构化：通过 LLM 将简历转成可编辑结构化数据。
- 简历优化：按技术岗、产品岗、运营岗、通用模板优化表达。
- JD 适配：根据岗位 JD 输出匹配分、弱项和优化建议。
- 模拟面试：基于简历经历和 RAG 知识库生成追问题。
- 回答评分：按完整性、逻辑性、一致性、简洁性、深度等维度评分。
- 面试报告：生成总结、薄弱点、改进建议，并支持 Markdown 导出。
- 账号治理：支持账号数据导出和账号注销，注销后审计记录匿名化。
- 组织管理：支持组织空间、成员列表、成员角色和组织级数据标识。
- 商业化闭环：支持权益额度、人工开通、支付订单、签名 webhook 自动开通套餐。
- 系统后台：提供发布检查、运营摘要、审计日志、成本估算、运行指标和备份入口。

## 技术栈

### 后端

- FastAPI
- SQLAlchemy Async
- Alembic
- SQLite / PostgreSQL
- Pydantic Settings
- 本地 RAG 检索
- 多 LLM Provider 适配：local、OpenAI、Moonshot、DeepSeek、Anthropic、custom

### 前端

- React 18
- Vite
- TypeScript
- TailwindCSS
- Zustand
- Axios
- lucide-react
- Playwright

## 项目结构

```text
.
├── backend/                 # FastAPI 后端
│   ├── app/
│   │   ├── routers/         # API 路由
│   │   ├── services/        # 业务服务
│   │   ├── models/          # SQLAlchemy 模型
│   │   ├── schemas/         # Pydantic Schema
│   │   └── utils/           # 工具函数
│   ├── alembic/             # 数据库迁移
│   └── tests/               # 后端单元/集成测试
├── frontend/                # React 前端
│   ├── src/
│   │   ├── pages/           # 页面
│   │   ├── components/      # 组件
│   │   ├── services/        # API Client
│   │   └── stores/          # 状态管理
│   └── e2e/                 # Playwright E2E
├── docs/                    # 产品、架构、安全、发布和运维文档
└── .github/workflows/       # CI 流水线
```

## 本地运行

### 后端

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

默认前端地址为 `http://127.0.0.1:5173`，后端地址为 `http://127.0.0.1:8000`。

## 测试与质量检查

```bash
# 后端
cd backend
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m alembic heads

# 前端
cd frontend
npm run typecheck
npm run build
npm audit --json
npm run e2e
```

当前项目已通过：

- 后端 unittest
- Alembic head 检查
- 前端 TypeScript 检查
- 前端生产构建
- npm audit
- Playwright E2E 冒烟测试

## 企业级能力

- 发布检查：生产环境阻断危险配置，如默认密钥、SQLite、公开 docs、不安全 CORS、未配置真实 LLM 等。
- 审计日志：记录认证、简历、面试、报告、账号、计费、支付、组织等关键事件。
- 账号合规：支持账号数据导出、账号删除和删除后的审计匿名化。
- 组织协作：支持组织实体、组织成员、角色和组织级资源标识。
- 商业化：支持套餐权益、额度扣减、人工开通、支付订单和签名 webhook。
- 运维：提供运行指标、备份状态、管理员备份接口、blue/green 和 canary 配置。
- CI/CD：GitHub Actions 覆盖后端、前端和 E2E。

## 上传 GitHub 前注意

不要提交真实 `.env`、本地数据库、日志、依赖目录、构建产物、测试报告和上传文件。根目录 `.gitignore` 已覆盖这些常见风险。

推荐首次上传前执行：

```bash
git status --ignored
git add .
git status
```

确认没有 `.env`、`*.db`、`node_modules/`、`dist/`、`.venv/`、`test-results/`、`playwright-report/` 出现在待提交列表后再 commit。
