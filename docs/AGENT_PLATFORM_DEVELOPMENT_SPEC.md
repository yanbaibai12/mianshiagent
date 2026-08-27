# 多 Agent 求职训练平台企业级开发规范

> 文档版本：1.4.0
> 状态：Phase 1A 已实施；Phase 1B 审计基础已实现；受控 Shadow API 与真实只读领域适配器已实现
> 编制日期：2026-08-27
> 适用仓库：`mianshiagent`
> 目标版本：Agent Platform v2
> 文档负责人：项目维护者
> 生效条件：本文档及 ADR-0001 经项目维护者批准
> 关联文档：[`QUALITY_GATE_STANDARD.md`](./QUALITY_GATE_STANDARD.md)、[`RESUME_REWRITE_EVALUATION.md`](./RESUME_REWRITE_EVALUATION.md)

---

## 1. 文档目的

本文档定义项目从“LLM + RAG 求职训练 SaaS”向“基于 Harness、MCP、Skills 的多 Agent 求职训练平台”演进时必须遵守的产品边界、系统架构、工程标准、安全要求、数据契约、开发流程、质量门和阶段计划。

本文档中的关键字按以下强度解释：

- **必须（MUST）**：不满足不得合并或发布。
- **禁止（MUST NOT）**：任何环境均不得违反。
- **应该（SHOULD）**：原则上执行，偏离时必须记录 ADR 和风险接受人。
- **可以（MAY）**：根据成本和阶段选择。

本项目以“输出真实、可验证、可复现”为最高优先级，不以功能数量、模型自评分或演示效果代替质量证明。

---

## 2. 产品重新定位

### 2.1 新定位

产品名称建议调整为：

> **Interview Agent Platform：基于 Harness、MCP 和 Skills 的多 Agent 求职训练系统**

核心价值不是管理会员、公司或运营数据，而是让多个受控 Agent 围绕用户真实简历和目标岗位完成：

1. 简历证据提取；
2. JD 能力模型构建；
3. 有证据约束的简历改写；
4. 面试计划制定；
5. 动态出题与追问；
6. 基于证据的回答评分；
7. 薄弱项分析和训练计划生成；
8. 全流程追踪、回放和评测。

### 2.2 核心成功指标

项目是否成功，必须由以下指标判断：

- 简历改写不存在新增虚构事实；
- 简历改写相对原文在盲评中获得显著偏好；
- JD 相关性提升来自已有证据，而不是关键词堆砌；
- 面试题能够引用简历或知识库证据；
- Agent 能正确选择工具、停止、失败降级和交接；
- 每次结果能够追踪到模型、Prompt、Skill、工具、证据和代码版本；
- 相同评测集上的质量不会因模型、Prompt 或 Skill 变更无声退化。

### 2.3 非目标

Agent Platform v2 阶段明确不建设：

- 支付、订单、套餐、发票、退款；
- 企业客户和销售管理；
- 多组织成员、复杂租户、机构账号池；
- 面向运营人员的商业运营后台；
- 面向用户的通用质量反馈运营闭环；
- 为展示“多 Agent”而把确定性业务强行 Agent 化；
- 无评测支撑的自动化扩权和自主外部写操作。

---

## 3. 当前系统基线

截至 2026-08-27，当前代码已经具备：

- FastAPI、SQLAlchemy Async、Alembic；
- React、TypeScript、Vite、Playwright；
- SQLite/PostgreSQL；
- Redis/RQ 异步任务；
- Qdrant、本地关键词检索、Embedding、Rerank；
- 多 LLM Provider；
- 简历解析、版本管理、JD 适配；
- 面试生成、作答评分、报告导出；
- 训练计划；
- 审计、发布检查和基础监控；
- 现有后端测试和 E2E 主链路。

当前主要架构问题：

1. 业务流程主要由 API 路由固定编排，模型负责生成内容，但没有统一 Agent 生命周期；
2. `interviews.py`、`resumes.py`、`llm_client.py` 等文件职责过重；
3. 工具调用、Prompt、业务代码和输出解析耦合；
4. 缺少统一的 Agent Run、Step、Handoff、Checkpoint、Budget 和 Trace 模型；
5. 简历优化有“不得虚构”提示，但缺少强制证据绑定和独立事实验证器；
6. 现有 ATS 评测可作为基础，但不能单独证明改写有效；
7. 文档与代码存在漂移，质量声明不能完全由 CI 证据自动生成；
8. 当前认证、进程内限流和部分本地 fallback 仍属于 MVP 等级。

---

## 4. 模块裁剪与保留决策

### 4.1 删除模块

以下模块进入退役范围。本文将用户提出的“公司管理”解释为“公司画像 CRUD + 组织/租户管理”；如果未来需要团队协作能力，必须另立 ADR 重新引入，不在 v2 默认范围内：

| 类别 | 后端范围 | 前端范围 | 数据范围 |
|---|---|---|---|
| 支付和商业化 | Phase 1A 已删除 `payments.py`、`business.py` Router/商业服务 | 套餐、升级、额度阻断和支付入口已删除 | 历史 `payment_orders`、`billing_accounts` 暂留，待 Phase 1B contract migration |
| 组织管理 | Phase 1A 已删除 `organizations.py`；`tenancy.py` 暂作内部隔离兼容 | `/organizations`、组织导航和组织管理服务已删除 | `organizations`、`organization_members` 暂留，个人组织不可作为产品能力暴露 |
| 公司画像管理 | Phase 1A 已删除公开 CRUD Router；内部 snapshot 兼容服务暂留 | `/company-profiles` 页面、路由和服务已删除 | `company_interview_profiles` 暂留，只用于历史兼容和受控内部匹配 |
| 运营后台 | 商业/质量运营 API 已退役；最小运维 API 保留 | `/admin/system` 已删除 | health、release check、alerts、backup 所需数据继续保留 |
| 用户质量反馈 | Phase 1A 已删除 `/api/quality/*` 产品 API | Job 页面质量反馈表单已删除 | 历史质量表暂留，未自动转为 Eval 数据 |

### 4.2 保留或转化模块

以下能力不能随 UI 一起删除：

- `audit_logs`：保留并扩展为 Agent 行为审计；
- `quality_eval_candidates`：迁移为离线评测样本，不再依赖用户运营流程；
- 系统健康检查：保留 `/health` 和最小发布检查；
- 请求指标：保留并扩展 Agent 指标；
- 公司信息：如确有面试价值，转成只读、可审计的 `company_research` MCP Tool，而不是 CRUD 模块；
- 额度概念：商业额度删除，但保留 Agent 单次运行的 token、步骤、时间和工具预算；
- 用户和账号数据治理：保留导出、删除和审计匿名化能力。

### 4.3 删除原则

模块删除必须分阶段完成：

1. 建立现有行为测试、契约基线和数据备份；
2. 从前端入口下线并删除产品调用方；
3. 对公开 API 删除逐项登记 Method + Path、owner、原因和 ADR；
4. 解除运行时业务依赖并保留必要的历史兼容边界；
5. 先验证当前 Schema、核心 E2E、账号治理和回滚路径；
6. 数据库变更独立采用 expand → migrate → contract；
7. 执行 PostgreSQL 升级、回滚和恢复演练后才允许 contract；
8. 删除代码、配置和文档残留并运行全量质量门。

禁止在一个提交中同时完成“删除大量模块”和“引入 Harness 核心”，两类变更必须可独立回滚。

---

## 5. 目标逻辑架构

```text
┌─────────────────────────────────────────────────────────────┐
│ React Client                                                │
│ 任务创建 / 实时进度 / 审批 / 面试交互 / Trace 查看          │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTPS / SSE
┌──────────────────────────────▼──────────────────────────────┐
│ FastAPI Application Boundary                                │
│ Auth / Resume / Job / Interview / Report / Agent Runs       │
└──────────────────────────────┬──────────────────────────────┘
                               │ Command
┌──────────────────────────────▼──────────────────────────────┐
│ Agent Harness                                               │
│ Run Engine | Planner | Scheduler | State | Budget | Policy  │
│ Retry | Timeout | Cancel | Checkpoint | Replay | Trace       │
└──────────────┬───────────────────────┬───────────────────────┘
               │                       │
┌──────────────▼───────────────┐ ┌────▼──────────────────────┐
│ Agent Registry              │ │ Skill Registry            │
│ Supervisor                  │ │ Resume Evidence           │
│ Resume Analyst              │ │ JD Competency Mapping     │
│ JD Analyst                  │ │ Truthful Rewrite          │
│ Interviewer                 │ │ Interview Design          │
│ Evaluator/Coach             │ │ Evidence Scoring          │
└──────────────┬───────────────┘ └────┬──────────────────────┘
               │                      │
┌──────────────▼──────────────────────▼───────────────────────┐
│ MCP Gateway / Tool Broker                                   │
│ Tool Allowlist | Approval | Auth | Schema | Timeout | Audit │
└──────────────┬──────────────────────────────┬───────────────┘
               │                              │
┌──────────────▼───────────────┐ ┌────────────▼──────────────┐
│ Domain MCP Servers          │ │ Deterministic Services     │
│ Resume / Job / Knowledge    │ │ Parser / ATS / Export      │
│ Interview / Artifact        │ │ Validators / Database      │
└──────────────┬───────────────┘ └────────────┬──────────────┘
               │                              │
┌──────────────▼──────────────────────────────▼───────────────┐
│ PostgreSQL | Redis/RQ | Qdrant | Object Storage | Telemetry │
└─────────────────────────────────────────────────────────────┘
```

### 5.1 架构原则

1. **确定性优先**：能用普通代码可靠完成的任务禁止交给 Agent。
2. **证据优先**：面向用户的事实性输出必须引用可信证据。
3. **最小权限**：Agent 只能看到当前任务所需的数据和工具。
4. **结构化输出**：Agent 间交接必须使用版本化 Schema，不使用自由文本作为唯一契约。
5. **可恢复**：长任务必须支持 checkpoint、幂等、重试和取消。
6. **可审计**：每个工具调用和状态改变都必须记录主体、输入摘要、结果、耗时和权限判定。
7. **可评测**：Agent、Skill、Prompt、模型和工具版本必须进入评测维度。
8. **人工可控**：外部写入、删除、高成本操作或敏感数据外发必须经过审批。
9. **模块化单体优先**：在并发和团队规模没有证明需要之前，不拆业务微服务；MCP Server 可先作为进程内适配器实现。

---

## 6. Agent Harness 设计

### 6.1 Harness 职责

Harness 必须统一提供：

- Agent 定义加载；
- Skill 加载和版本锁定；
- MCP Tool 发现、筛选和调用；
- Run/Step 状态机；
- 上下文构建和压缩；
- token、耗时、步骤和工具调用预算；
- 同步、异步、串行和并行执行；
- retry、timeout、cancellation；
- checkpoint 和 resume；
- handoff；
- 输出 Schema 验证；
- 审批策略；
- 全链路 trace；
- 评测 hook；
- 失败降级和安全终止。

### 6.2 Agent 定义契约

```python
class AgentDefinition(BaseModel):
    id: str
    version: str
    name: str
    objective: str
    instructions_ref: str
    skill_refs: list[str]
    allowed_tools: list[str]
    output_schema: str
    max_steps: int
    max_tool_calls: int
    timeout_seconds: int
    token_budget: int
    approval_policy: str
    retry_policy: str
```

Agent 定义必须不可变版本化。生产 Run 必须保存实际使用的定义快照或内容哈希。

### 6.3 Run 状态机

```text
CREATED
  → VALIDATING
  → QUEUED
  → RUNNING
      → WAITING_TOOL
      → WAITING_APPROVAL
      → WAITING_USER
      → HANDOFF
      → CHECKPOINTED
  → SUCCEEDED | FAILED | CANCELLED | EXPIRED
```

状态转换要求：

- 每个转换必须原子化并写入事件表；
- 重复请求必须通过 idempotency key 返回同一结果；
- worker 崩溃后必须从最后一个已提交 checkpoint 恢复；
- `SUCCEEDED` 必须同时满足业务输出 Schema 和质量策略；
- 超出预算必须进入 `FAILED` 或返回结构化 `PARTIAL_RESULT`，禁止静默截断；
- 用户取消后，未开始的工具调用必须停止，已执行写操作必须记录实际结果。

### 6.4 上下文模型

```python
class RunContext(BaseModel):
    run_id: UUID
    user_id: UUID
    objective: str
    resume_id: UUID | None
    job_id: UUID | None
    interview_id: UUID | None
    evidence_refs: list[str]
    artifact_refs: list[str]
    completed_steps: list[str]
    unresolved_questions: list[str]
    budgets: dict[str, int]
    policy_snapshot: dict
```

禁止把完整数据库对象、所有历史会话或不相关简历直接塞进模型上下文。Context Builder 必须执行：

- 用户和资源权限过滤；
- PII 分类；
- 文本长度和 token 限制；
- Prompt Injection 风险标注；
- 来源与证据 ID 标注；
- 去重和时效性检查；
- 完整输入的哈希记录。

### 6.5 预算

每次 Run 至少限制：

- 最大模型调用次数；
- 最大工具调用次数；
- 最大总 token；
- 最大并发子任务；
- 最大重试次数；
- 最大执行时间；
- 最大检索结果数量；
- 最大外发敏感字段数量。

预算到达 80% 时记录 warning；到达 100% 时强制终止或请求用户批准追加预算。

---

## 7. 多 Agent 角色

### 7.1 Supervisor Agent

职责：

- 将用户目标转换成执行计划；
- 判断哪些任务确定性执行、哪些需要 Agent；
- 并行调度 Resume Analyst 和 JD Analyst；
- 汇总输出并决定是否进入 Interviewer；
- 控制预算和终止条件；
- 不直接改写简历或评分，避免成为全能 Agent。

允许工具：只读任务状态、创建子 Run、读取结构化结果、请求用户补充信息。

### 7.2 Resume Analyst Agent

职责：

- 识别简历事实、实体、时间线、技术栈和成果；
- 建立证据图；
- 标注不确定、缺失和矛盾信息；
- 不直接创造不存在的指标和职责。

输出必须包含 `evidence_id`、原始来源、置信度和风险标记。

### 7.3 JD Analyst Agent

职责：

- 将 JD 拆分为职责、硬要求、加分项、领域知识和行为能力；
- 区分“必须匹配”和“可学习”；
- 生成能力矩阵，不直接修改简历；
- 输出每个要求的原文位置和重要度。

### 7.4 Interviewer Agent

职责：

- 基于简历证据、JD 能力矩阵和历史回答动态出题；
- 判断是否追问、切换模块或结束；
- 控制覆盖度、难度、重复率和追问深度；
- 每道问题必须记录来源和考察意图。

禁止一次性无差别生成大量题目作为“动态 Agent”的替代品。

### 7.5 Evaluator/Coach Agent

职责：

- 按题目、回答、简历证据和评分 Rubric 给出评分；
- 区分事实错误、表达问题和知识缺口；
- 给出可执行训练建议；
- 不因答案字数长而自动高分；
- 不得把参考答案中的新事实写入候选人的真实经历。

### 7.6 Critic

Critic 第一阶段作为 Harness 内部校验步骤，不独立成为常驻 Agent。仅在以下情况触发：

- 简历改写；
- 面试评分低置信度；
- Agent 输出包含新增数字、实体或时间；
- 多个 Agent 输出矛盾；
- 结果将被持久化或导出。

---

## 8. MCP 设计规范

### 8.1 MCP Server 划分

| Server | 主要能力 | 初始形态 |
|---|---|---|
| `resume-mcp` | 读取简历、检索证据、保存候选版本 | 进程内适配器，后续独立服务 |
| `job-mcp` | 读取 JD、能力矩阵和岗位状态 | 进程内适配器 |
| `knowledge-mcp` | RAG 检索、题库检索、来源读取 | 现有知识服务适配 |
| `interview-mcp` | 会话、题目、回答、评分和进度 | 进程内适配器 |
| `artifact-mcp` | DOCX/PDF/Markdown 导出 | 独立受限 worker |
| `company-research-mcp` | 可选的只读公司信息研究 | 后续阶段，默认关闭 |

### 8.2 工具契约

每个 Tool 必须声明：

- `name` 和版本；
- 使用场景和禁止场景；
- 输入 JSON Schema；
- 输出 JSON Schema；
- 权限范围；
- 是否有副作用；
- 是否幂等；
- 超时和重试策略；
- 数据分类；
- 审批级别；
- 可能错误及错误码；
- 审计字段；
- owner。

示例：

```json
{
  "name": "resume.search_evidence.v1",
  "risk": "read_sensitive",
  "side_effect": false,
  "idempotent": true,
  "approval": "run_scope",
  "timeout_ms": 3000,
  "input": {
    "resume_id": "uuid",
    "query": "string",
    "top_k": "integer<=10"
  },
  "output": {
    "items": [
      {
        "evidence_id": "string",
        "section": "string",
        "text": "string",
        "score": "number"
      }
    ]
  }
}
```

### 8.3 工具风险分级

| 等级 | 示例 | 默认策略 |
|---|---|---|
| R0 公开只读 | 读取公开模板 | 自动允许 |
| R1 用户私有只读 | 读取简历、回答 | Run 级授权、全量审计 |
| R2 可撤销写入 | 保存草稿、创建题目 | 明确目标资源、幂等 |
| R3 敏感或外部写入 | 发送消息、外部发布 | 每次人工审批 |
| R4 破坏性操作 | 删除、覆盖、批量导出 | 二次确认、短时令牌、禁止自动重试 |

### 8.4 MCP 安全要求

- HTTP MCP 必须使用 HTTPS 和符合当前规范的授权机制；
- 访问令牌必须校验 audience；
- 禁止 token passthrough；
- 工具描述、资源内容和工具输出均视为不可信输入；
- MCP Server 不得获得数据库超级用户权限；
- Agent 不能通过 Tool 参数绕过当前用户和资源范围；
- 所有写工具必须接受 idempotency key；
- 所有工具调用必须设置超时、最大响应大小和并发限制；
- 外部 URL 工具必须防止 SSRF、DNS rebinding 和私网探测；
- 未登记 Server、未固定版本或未通过安全评审的工具不得进入生产。

---

## 9. Skills 设计规范

### 9.1 Skill 定义

Skill 是版本化、可复用、可评测的专业执行规范，不是业务服务，也不是长期运行 Agent。

建议目录：

```text
skills/
├── resume-evidence-extraction/
│   ├── SKILL.md
│   ├── schemas/
│   ├── examples/
│   └── evals/
├── truthful-resume-rewrite/
├── jd-competency-mapping/
├── interview-question-design/
├── evidence-based-answer-scoring/
└── training-plan-generation/
```

### 9.2 Skill 必备内容

每个 `SKILL.md` 必须包含：

1. 适用范围；
2. 不适用范围；
3. 输入契约；
4. 输出契约；
5. 必须遵守的事实和安全约束；
6. 可用工具；
7. 操作步骤；
8. 停止条件；
9. 失败处理；
10. 正例、反例和边界案例；
11. 评测集位置；
12. 版本和变更记录。

### 9.3 首批 Skills

| Skill | 目标 | 发布前最低评测 |
|---|---|---|
| `resume-evidence-extraction` | 提取可引用事实 | 证据召回、实体和时间线准确率 |
| `truthful-resume-rewrite` | 有证据的简历改写 | 事实保持、盲评、ATS、JD 相关性 |
| `jd-competency-mapping` | JD 能力模型 | 要求抽取准确率和优先级一致性 |
| `interview-question-design` | 生成递进式、有依据的问题 | 覆盖度、重复率、证据率、难度 |
| `evidence-based-answer-scoring` | 可靠评分和建议 | 专家一致性、稳定性、解释充分度 |
| `training-plan-generation` | 生成可执行计划 | 任务可完成性、薄弱项覆盖率 |

Skill 变更必须独立版本化，并触发关联评测集；不得只修改 Prompt 后直接上线。

---

## 10. 数据模型建议

新增或重构以下核心表：

### 10.1 Agent 定义

- `agent_definitions`
- `agent_definition_versions`
- `skill_definitions`
- `skill_versions`
- `mcp_servers`
- `mcp_tools`

### 10.2 运行与追踪

- `agent_runs`
- `agent_steps`
- `agent_events`
- `agent_handoffs`
- `agent_tool_calls`
- `agent_checkpoints`
- `agent_approvals`
- `agent_artifacts`

### 10.3 评测

- `eval_suites`
- `eval_cases`
- `eval_runs`
- `eval_case_results`
- `eval_judgments`
- `quality_gate_reports`

### 10.4 简历证据

- `resume_evidence`
- `resume_rewrite_candidates`
- `resume_rewrite_claims`
- `resume_rewrite_reviews`

重要字段必须包含：

- `user_id`；
- 资源 owner；
- `model_provider/model_name/model_revision`；
- `prompt_version`；
- `agent_version`；
- `skill_versions`；
- `tool_versions`；
- `code_commit`；
- 输入和输出哈希；
- 状态、错误分类和时间戳。

模型推理原始内容不作为默认持久化字段；只保存完成审计和复现所需的结构化事件，避免泄露敏感推理和用户数据。

---

## 11. API 设计

建议新增：

```text
POST   /api/agent-runs
GET    /api/agent-runs/{run_id}
GET    /api/agent-runs/{run_id}/events
POST   /api/agent-runs/{run_id}/cancel
POST   /api/agent-runs/{run_id}/resume
POST   /api/agent-runs/{run_id}/approvals/{approval_id}
GET    /api/agent-runs/{run_id}/artifacts
POST   /api/resumes/{resume_id}/rewrite-runs
GET    /api/resumes/{resume_id}/rewrite-runs/{run_id}
POST   /api/interviews/{interview_id}/next-turn
```

API 规范：

- 创建类 API 必须支持 `Idempotency-Key`；
- 长任务返回 `202 Accepted` 和 `run_id`；
- 状态读取必须支持 ETag 或版本号；
- 进度使用 SSE，轮询作为 fallback；
- 所有错误返回稳定错误码、可重试标记和 `request_id`；
- 禁止直接向客户端暴露模型供应商原始异常；
- Agent 输出必须先通过 Schema 和政策验证再持久化；
- API 合约必须生成 OpenAPI，并进入契约测试。

---

## 12. 安全、隐私与合规

### 12.1 安全基线

Web 应用安全以 OWASP ASVS 5.0.0 的适用控制为基线；生成式 AI 风险管理参考 NIST AI RMF 和 NIST AI 600-1；Agent 额外覆盖 Prompt Injection、敏感信息泄露、供应链、输出处理和 Excessive Agency。

### 12.2 数据分类

| 级别 | 数据 | 要求 |
|---|---|---|
| S3 高敏 | 简历原文、联系方式、回答、报告 | 加密、最小访问、严禁完整日志 |
| S2 敏感 | 结构化经历、评分、弱点、证据 | 用户隔离、审计、有限保留 |
| S1 内部 | Prompt、Skill、评测结果、Trace 摘要 | 权限控制、版本管理 |
| S0 公开 | 公共题库、公开模板 | 完整性校验 |

### 12.3 强制安全控制

- 生产认证必须支持短时 access token、refresh token 轮换和撤销；
- 管理权限不得继续只依赖邮箱字符串；
- Token 不应长期保存在 `localStorage`；
- Redis/网关限流替代进程内限流；
- Prompt、Skill、MCP Server 包和模型配置必须做供应链审查；
- 模型输入中的简历、JD、知识库和工具结果都必须标记为不可信数据；
- 输出进入 HTML、Markdown、DOCX、SQL 或命令前必须做上下文相关编码与验证；
- 不允许模型直接生成和执行 SQL、Shell 或任意代码；
- 删除和批量导出必须人工确认；
- Secret 必须来自密钥管理系统或部署 Secret，不进入 Git、Trace 和模型上下文；
- 生产日志不得包含完整简历、JD、回答、Token、API Key 或文件正文。

---

## 13. 可观测性与 SLO

### 13.1 Trace

每个 Run 必须关联：

```text
request_id → run_id → agent_step_id → tool_call_id → artifact_id
```

必须记录：

- Agent/Skill/Prompt/模型版本；
- 输入输出哈希；
- 工具名称和版本；
- 状态、耗时、token、重试；
- 证据 ID；
- 审批和政策判定；
- 错误分类；
- 最终质量门结果。

### 13.2 初始 SLO

| 指标 | Beta 目标 |
|---|---:|
| 核心 API 月可用性 | ≥ 99.9% |
| Agent Run 可恢复率 | ≥ 99.5% |
| 非模型 API p95 | ≤ 500ms |
| Run 入队 p95 | ≤ 2s |
| 工具调用成功率（排除业务拒绝） | ≥ 99.0% |
| Trace 完整率 | 100% |
| 未授权跨用户数据访问 | 0 |
| 未经审批的 R3/R4 操作 | 0 |

质量指标优先于延迟；不允许通过跳过事实验证来降低响应时间。

---

## 14. 工程开发标准

### 14.1 Git

- 功能开发从最新集成基线创建独立分支；
- 分支使用 `feature/`、`fix/`、`hotfix/`；
- 一个需求一个分支，不混合删除模块和 Harness 重构；
- 禁止直接推送受保护分支；
- 提交信息使用 `<type>(<scope>): <中文动作描述>`；
- 所有合并必须通过质量门和代码评审。

### 14.2 代码组织

目标结构建议：

```text
backend/app/
├── agents/
│   ├── definitions/
│   ├── supervisor.py
│   ├── resume_analyst.py
│   ├── jd_analyst.py
│   ├── interviewer.py
│   └── evaluator_coach.py
├── harness/
│   ├── engine.py
│   ├── state.py
│   ├── scheduler.py
│   ├── context.py
│   ├── policy.py
│   ├── budget.py
│   ├── checkpoint.py
│   └── tracing.py
├── mcp/
│   ├── gateway.py
│   ├── registry.py
│   ├── policy.py
│   └── servers/
├── skills/
├── evals/
└── domains/
    ├── resume/
    ├── job/
    ├── interview/
    ├── training/
    └── knowledge/
```

单文件超过 500 行必须评审是否拆分；超过 800 行原则上禁止继续增加业务逻辑。

### 14.3 ADR

以下决策必须写 Architecture Decision Record：

- 选择或自研 Harness；
- MCP Server 边界；
- Agent 拆分；
- 模型和供应商；
- 上下文持久化策略；
- 认证方案；
- 评测模型是否参与发布门；
- PostgreSQL/Redis/Qdrant 部署拓扑；
- 任何降低安全或质量阈值的例外。

---

## 15. 开发计划

基准计划以 2026-08-27 为计划开始日期。若审批日期晚于 2026-08-27，项目负责人必须在 Phase 0 重新基线化日期并整体顺延；不得通过压缩测试、评测或灰度时间追回进度。每阶段必须独立通过对应质量门，未通过不得提前进入后续阶段。

### Phase 0：基线冻结与治理

**日期：2026-08-26 至 2026-09-04**
**当前状态：基线工程已实施、尚未提交；2026-08-27 后端、前端和契约 Release Gate 均已通过。**

交付物：

- 当前 API、数据库和主链路清单；
- 待删除模块依赖图；
- 文档入口和所有者；
- 后端 Ruff、类型检查、覆盖率；
- 前端 lint、单元测试基础；
- 修复当前 npm high 漏洞；
- 质量门 CI 骨架；
- Agent v2 ADR-0001。

退出标准：

- 当前核心链路全部可复现；
- CI 没有 high/critical 依赖漏洞；
- 质量门能够生成机器可读报告；
- 所有现存测试通过。

Phase 0 当前事实基线：

- 历史冻结基线为 17 个 Router 模块、97 个 Router 装饰器、98 个 OpenAPI operation、26 张业务表和 Alembic head `0017`；当前活动快照为 29 张表（26 张历史业务表 + 3 张 Agent Runtime 表）和唯一 head `0018`；
- 最新后端 Release Gate：116 个 pytest 测试和 19 个 subtests 通过，总行覆盖率 `86.03% >= 85%`；CI ratchet 仍保持 64%，Release 阈值保持 85%；
- Ruff lint 全量通过；Ruff format/mypy 已纳管 Agent Platform 与既有受控内核，共 20 个 mypy source files；存量全量格式/类型债务仍需分阶段收敛；
- 前端 lint、7 个单测、typecheck、build、npm audit 和 3 个 Chromium E2E 场景通过；
- Python/npm 已知高危漏洞为 0，Secret scan finding 为 0；
- OpenAPI 兼容校验器已启用；当前从 98 项历史契约收缩为 79 项活动 operation，19 项删除均有 ADR-0002 精确批准，未批准 breaking change 为 0；
- Agent、MCP、Skills 注册表均为 `active`：5 个 Agent、4 个 Skill、2 个只读 MCP-compatible Tool；入口、SemVer、handoff、allowlist、审批和输入输出契约均受阻断校验；
- Agent shadow fact-safety 自动评测 8/8 通过；该结果只证明事实安全不变量，不证明招聘者偏好、ATS 提升或人工感知效果；
- 详细证据见 `BASELINE_INVENTORY.md`，退役顺序见 `MODULE_RETIREMENT_DEPENDENCIES.md`。

### Phase 1A：产品表面退役

**实际实施日期：2026-08-27**
**当前状态：已实施、未提交；ADR-0002 Accepted。**

已交付：

- 删除支付、商业套餐、升级和 entitlement 阻断；
- 删除组织管理、多租户 UI 和公开 API；
- 删除公司画像 CRUD 页面和公开 API，保留历史 snapshot 内部兼容；
- 删除运营后台 UI，保留最小 health、status、release check、alerts、backup 能力；
- 删除面向用户的质量反馈 UI/API；
- OpenAPI 98 → 79，19 项删除逐项批准，未批准 breaking change 为 0；
- 更新后端回归、质量工具测试和 3 个核心 E2E 场景。

已满足的退出标准：

- 简历、岗位、面试、报告和训练计划不再依赖商业 entitlement；
- 退役前端引用扫描为 0；
- 19 个退役 API 返回 404 且不再出现在 OpenAPI；
- 账号导出、账号删除、历史画像 snapshot 和运维能力回归通过；
- 后端 Release Gate 总行覆盖率已提升至 `86.03%`，同时满足 64% CI ratchet 和 85% Release 门。

### Phase 1B：历史数据契约迁移

**计划日期：2026-09-07 至 2026-09-18**
**当前状态：只读审计基础已实现；Agent Runtime 的 Alembic `0018` 已新增，但 Phase 1B 历史数据 contract migration 与真实数据迁移仍未开始。**

已完成的前置基础：

- 新增只读 Phase 1B 数据契约审计服务和 CLI；
- 覆盖 26 张表 row count、全量外键孤儿、组织成员映射、共享组织、公司画像归属和父子实体 owner 一致性；
- 默认 blocker 退出码为 1、Schema/读取失败退出码为 2；报告带 SHA-256 证据哈希；
- 9 个自动化测试通过；尚未在真实 PostgreSQL 数据副本上执行。

剩余交付物：

- 个人用户所有权 expand migration 或兼容视图；
- 历史组织、支付、质量和公司画像数据分类、导出和迁移报告；
- row count、孤儿记录、重复映射与账号导出核对；
- PostgreSQL 升级、降级、备份恢复演练；
- 独立 contract ADR 与 Alembic 迁移；
- 消费并归档 OpenAPI 删除批准清单，冻结新的 v2 契约基线。

退出标准：

- 数据迁移前后记录数量和归属一致；
- 账号数据导出与删除仍然正确；
- 无跨用户数据泄露或悬空外键；
- contract migration 可回滚，恢复演练有证据；
- 不与 Harness 核心实现混入同一原子提交。

### Phase 2：Harness 核心

**日期：2026-09-21 至 2026-10-09**

交付物：

- Agent Definition Registry；
- Run/Step/Event 状态机；
- Budget、Retry、Timeout、Cancel；
- Checkpoint 和 Resume；
- Redis/RQ Agent durable worker；
- Trace 和 Run Inspector 最小页面；
- 生产 Agent API。

已提前实现的受控 Shadow Slice（不代表 Phase 2 完成）：

- 5 个 Agent、4 个 Skill、2 个只读 MCP-compatible Tool 的隔离运行时；
- 本地 `InMemoryRunStore` 与可配置 `PostgresRunStore`；后者已实现事务幂等、持久化 Step/Trace/Checkpoint、执行租约、过期接管、stale owner 拒绝、取消竞争和失败重试；
- 预算、超时、取消、有限重试、规范化请求指纹、Checkpoint、Trace 和进程内并发串行化；
- 真实 Resume/Interview 数据库只读适配器，执行 Run user、Tool audience、双向 allowlist 和数据库 owner 校验；
- 认证、默认关闭、隐藏 OpenAPI 的 `/api/agent-shadow/runs*`；
- 同用户 Run 隔离、公共错误码和内部状态/异常脱敏；
- 生产环境启用 Shadow API 时由 Release Check 和启动检查双重阻断。

以上 Slice 仍仅用于契约验证。PostgreSQL Run Store、事务幂等和 execution lease 已完成代码实现，但真实 PostgreSQL 升级/降级、多实例并发、租约接管、取消竞争与恢复演练仍缺失；durable worker、kill/restart、重复投递恢复、Run Inspector 和生产 Agent API 也未完成。因此下面的 Phase 2 退出标准仍不得整体标记完成。

退出标准：

- worker 强制终止后 Run 可恢复；
- 重复提交不产生重复副作用；
- 所有状态转换通过属性和并发测试；
- Trace 完整率 100%。

### Phase 3：MCP Gateway 与 Skills

**日期：2026-10-12 至 2026-10-30**

交付物：

- MCP Registry 和 Gateway；
- Resume、Job、Knowledge、Interview MCP 适配器；
- 工具 allowlist、审批和风险分级；
- 首批六个 Skills；
- Tool/Skill 版本和评测钩子；
- Prompt Injection 和越权安全测试。

当前提前完成的 Shadow 子集：Registry/Gateway、4 个 Skills、2 个真实只读领域适配器、audience/allowlist/owner 校验和跨用户拒绝测试。Job/Knowledge 适配器、网络 MCP Server、首批六个 Skills 和生产级取消/SLO 仍未完成。

退出标准：

- 每个 Agent 只能看到允许工具；
- R3/R4 工具未经批准调用成功率为 0；
- 工具输入输出 Schema 验证覆盖率 100%；
- 工具跨用户访问测试全部拒绝。

### Phase 4：多 Agent 面试闭环

**日期：2026-11-02 至 2026-11-20**

交付物：

- Supervisor；
- Resume Analyst；
- JD Analyst；
- Interviewer；
- Evaluator/Coach；
- 并行分析和 handoff；
- 动态追问和终止策略；
- Agent routing、tool selection、handoff 评测集。

退出标准：

- 多 Agent 相对固定工作流在目标评测集上有统计意义的质量提升；
- Agent 不重复执行已完成任务；
- 动态追问覆盖度和重复率达到质量门；
- 故障、超时、取消和降级 E2E 通过。

### Phase 5：真实有效的简历改写

**日期：2026-11-23 至 2026-12-11**

交付物：

- Resume Evidence Graph；
- Claim-level provenance；
- 事实验证器和 Critic；
- 改写 Rubric；
- 至少 120 条分层评测样本；
- 盲评工具；
- Prompt/Skill/模型对比报告；
- 安全 fallback。

退出标准：

- 满足 `RESUME_REWRITE_EVALUATION.md` 全部阻断阈值；
- 任何新增数字、公司、时间、职位和技能必须有证据；
- 盲评胜率和置信区间达标；
- 任一用户群体不存在显著退化。

### Phase 6：生产加固与受控 Beta

**日期：2026-12-14 至 2026-12-31**

交付物：

- 成熟认证、Redis 限流、Secret 管理；
- PostgreSQL、Redis、Qdrant 备份恢复；
- 负载、混沌和灾难恢复测试；
- 安全评审和隐私检查；
- 发布 Runbook；
- 受控 Beta、监控和回滚方案。

退出标准：

- 所有 P0/P1 风险关闭；
- SLO 和安全门通过；
- 发布回滚演练通过；
- 产品只对受控用户开放，模型和 Skill 变更受版本门控制。

---

## 16. Definition of Done

任何功能只有同时满足以下条件才能标记完成：

- 需求和验收标准明确；
- 架构和数据契约已评审；
- 代码、迁移、配置和文档同步；
- 单元、集成、契约、E2E 和相关 eval 通过；
- 安全和隐私检查通过；
- 有监控、错误分类和回滚方式；
- 完整 diff 已人工评审；
- 没有未记录的高风险例外；
- 质量门报告可追踪到 commit；
- 用户可见结果满足事实性和效果标准。

“代码已写完”“能运行”“模型看起来回答不错”均不构成完成。

---

## 17. 风险登记

| 风险 | 影响 | 缓解 |
|---|---|---|
| 为展示多 Agent 过度拆分 | 成本、延迟、故障上升 | 用评测证明每个 Agent 的增量价值 |
| 简历改写虚构事实 | 用户职业和信誉风险 | Claim 级证据、独立验证、阻断发布 |
| MCP 工具越权 | 简历泄露或破坏性操作 | 最小权限、审批、audience、全量审计 |
| Prompt Injection | 工具滥用、数据外泄 | 输入隔离、工具 allowlist、输出验证 |
| Agent 循环失控 | 成本和可用性风险 | 步骤、token、时间和调用预算 |
| 多模型结果不稳定 | 回归和用户体验波动 | 版本锁定、固定 eval、灰度发布 |
| 删除旧模块破坏主链路 | 功能回归 | 分阶段退役、迁移和 E2E |
| 评测被内部 ATS 指标绑架 | “分数提高但简历变差” | 盲评、事实性、真实用户行为多指标 |
| Trace 泄露敏感信息 | 合规风险 | 摘要化、脱敏、访问控制和保留策略 |

---

## 18. 标准参考

本项目应定期复核以下官方标准；引用版本变化时必须通过 ADR 更新基线：

- OpenAI API Model Guidance：`https://developers.openai.com/api/docs/guides/latest-model`
- OpenAI Responses API：`https://developers.openai.com/api/reference/resources/responses/methods/create`
- Model Context Protocol Specification 2026-07-28：`https://modelcontextprotocol.io/specification/2026-07-28`
- NIST AI Risk Management Framework：`https://www.nist.gov/itl/ai-risk-management-framework`
- NIST AI 600-1 Generative AI Profile：`https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf`
- OWASP ASVS 5.0.0：`https://owasp.org/www-project-application-security-verification-standard/`
- OWASP Top 10 for LLM Applications 2025：`https://genai.owasp.org/llm-top-10/`

---

## 19. 立即执行的下一步

1. 对本工作区运行后端、前端、契约 Release Gate 和 Chromium E2E，并将机器可读 Artifact 绑定最终 commit；
2. 在只读审计基础上完成真实 PostgreSQL 数据审计、升级、降级和恢复演练；在此之前不得执行破坏性 contract migration；
3. 在已实现 PostgreSQL Run Store、事务幂等和 execution lease 的基础上，完成真实 PostgreSQL 多实例/取消竞争/恢复演练，并实现 durable worker、重复投递保护和强制终止恢复测试；
4. 明确网络 MCP Server 或经评审的进程内生产边界，并补齐 Job/Knowledge adapters、可取消 I/O 与服务级 SLO；
5. 建立至少 120 条分层简历 Evidence/Claim 样本和人工双盲评测，报告 95% 置信区间与群体退化；
6. 在 Shadow 比较、成本、SLO、安全、数据和 AI 效果门全部通过前，保持 `AGENT_SHADOW_API_ENABLED=false`，不得以 Agent Harness 替换稳定主链路；
7. 完成完整 diff 人工评审，确认没有通过 Mock、SQLite、降低阈值、删除测试或排除核心代码伪造生产完成度。
