# Agent Platform v2 基线、Phase 1A 与 Phase 1B 审计清单

> 文档版本：1.6.0
> 状态：Phase 0 与 Phase 1A 已合并；Phase 1B 审计基础已实现；Run Inspector API 为发布候选
> 基线日期：2026-08-26
> 当前快照日期：2026-08-27
> Git 集成基线：`11bf353`（`main` / `origin/main`）
> 发布候选分支：`feature/agent-run-inspector`
> Owner：Agent Platform Team
> 机器可读清单：[`../backend/quality/baseline-manifest.json`](../backend/quality/baseline-manifest.json)

## 1. 基线声明

本清单同时记录两个不可混淆的事实集合：

1. **历史冻结基线**：Agent Platform v2 收缩前的契约与代码规模，用于解释兼容性变化；
2. **当前活动快照**：产品表面退役并加入 Phase 1B 只读审计基础后的工作区状态，用于质量门和后续开发计划。

Phase 0 与 Phase 1A 已通过 Pull Request #1 合并到 `main`。当前活动快照新增用户隔离、筛选和游标分页的 Run Inspector API；本地 Release Gate 报告记录工作区指纹，正式合并仍必须由 Pull Request GitHub Actions 将证据绑定最终 commit。任何数量、覆盖率或安全结论均以实际执行结果为准，不以文档声明替代 CI 证据。

## 2. 代码与契约规模

| 项目 | 历史基线 | 2026-08-27 活动值 | 证据/来源 |
|---|---:|---:|---|
| FastAPI Router 模块 | 17 | 12 | `backend/app/main.py` 与 `backend/app/routers/*.py` |
| Router 装饰器 | 97 | 78 | AST 静态盘点 |
| OpenAPI Operation | 98 | 79 | 冻结基线、运行时 Schema 与兼容报告 |
| 批准删除的 Operation | 0 | 19 | `quality/openapi-approved-removals.json`、ADR-0002 |
| 数据表 | 26 | 29 | 26 张历史业务表未删除；Alembic `0018` 新增 3 张 Agent Runtime 表 |
| Alembic Head | `0017` | `0018` | `python -m alembic heads` |
| Alembic 版本文件 | 17 | 18 | `backend/alembic/versions` |
| 前端 TS/TSX 文件 | 44 | 36 | `frontend/src` |
| 前端页面 | 未单列 | 12 | `frontend/src/pages/*.tsx` |
| ATS 评测样本 | 40 | 40 | `backend/quality/ats_eval_cases.json` |

### 2.1 当前活动 API Router

`account`、`audit`、`auth`、`community`、`interviews`、`jobs`、`knowledge`、`resumes`、`system`、`tasks`、`templates`、`training_plans`。

以下公开 Router 已在 Phase 1A 停止注册并删除实现：`business`、`company_profiles`、`organizations`、`payments`、`quality`。

OpenAPI 兼容策略仍以 98 项历史契约为冻结基线。经 ADR-0002 精确批准的 19 项 `operation_removed` 可从阻断集合中分离；任何未批准删除，以及参数、Security、请求体、响应体、响应头等非删除型破坏性变化仍必须阻断。

### 2.2 当前数据表

当前 SQLAlchemy 元数据共 29 张表。其中 26 张是历史业务表，继续包含 `billing_accounts`、`payment_orders`、`organizations`、`organization_members`、`company_interview_profiles`、`quality_annotations` 和 `quality_eval_candidates`；这是 ADR-0002 明确要求的非破坏性兼容窗口，不代表这些表仍是活动产品能力。Alembic `0018` 另外新增 `agent_runs`、`agent_run_steps` 和 `agent_run_trace_events` 3 张 Agent Runtime 表。

Phase 1B 只能按 expand → migrate → contract 执行数据契约收缩，并必须提供行数核对、孤儿记录检查、备份恢复和回滚证据。

## 3. Phase 1A 验收状态

### 3.1 已实施

- 删除支付、套餐、商业权益、组织管理、公司画像 CRUD、运营后台 UI 和用户质量反馈的前端入口；
- 删除 5 个退役后端 Router、2 个商业服务以及对应前端页面/服务；
- 核心简历、JD、面试、报告和训练计划流程不再执行 entitlement 检查；
- 新增 operational usage telemetry，只记录使用事实，不执行商业授权；
- 19 个退役 API operation 返回 404，并从当前 OpenAPI Schema 消失；
- OpenAPI 删除采用机器可读批准清单，未批准 breaking change 为 0；
- 历史公司画像 snapshot、personal organization 隔离、账号导出和历史数据仍保持兼容；
- 核心 E2E 已移除质量反馈步骤，并验证退役入口不存在。

### 3.2 明确未实施

- 数据库 expand/migrate/contract migration、删表、删列或外键收缩；真实 PostgreSQL 数据副本审计也尚未执行；
- Phase 1B 历史数据 expand/migrate/contract migration、真实 PostgreSQL 数据副本审计和恢复演练；
- Agent durable worker、kill/restart、重复投递恢复、Run Inspector UI 和生产 Agent API；
- 网络 MCP Server 或正式批准的进程内生产服务边界；
- Evidence Graph 和经独立人工双盲证明有效的简历改写生产链路。

## 4. 质量快照

| 检查 | 2026-08-27 实测结果 | 说明 |
|---|---:|---|
| 后端测试 | 118 passed / 24 subtests passed | pytest 全量；含 Agent shadow runtime、文档治理和 Phase 1B 数据审计测试 |
| 后端行覆盖率 | 86.15% | Release Gate 实测；CI ratchet 仍固定为 64% |
| 后端 Ruff lint | 通过 | `app tests scripts` |
| 后端 Ruff format | 通过 | 12 个既有受控内核模块 + Agent Platform/Shadow API；contracts scripts 独立全量检查 |
| 后端 mypy | 通过 | 20 个受控 source files，覆盖 Agent Platform 与既有受控内核 |
| 数据库版本 fail-closed 测试 | 3 passed | 多 head、版本表不可读、数据库落后均阻断启动 |
| Python 依赖漏洞 | 0 known | `pip-audit --local --strict --vulnerability-service osv` |
| Alembic head | 1 | `0018` |
| 前端 ESLint | 通过 | 0 error / 0 warning |
| 前端单元测试 | 7 passed | Vitest，2 个 test files |
| 前端 TypeScript | 通过 | `tsc --noEmit` |
| 前端生产构建 | 通过 | Vite build |
| 前端 E2E | 3 passed | Chromium；`smoke`、`training-plan`、`free-flow` |
| npm 漏洞 | 0 | `npm audit --audit-level=high` |
| Secret scan | 0 finding | 高置信度规则 |
| OpenAPI compatibility | 通过 | 98 → 79；19 项批准删除；0 项未批准 breaking change |
| Agent Registry | active shadow runtime | 5 agents；真实 entrypoint 与 handoff 契约已校验 |
| Skills Registry | active shadow runtime | 4 skills；SKILL.md、输入输出和 SemVer 已校验 |
| MCP Tool Registry | active shadow runtime | 2 个只读工具；Agent allowlist 与 audience 契约已校验 |
| 质量工具、平台、Run Inspector 与数据审计测试 | 已纳入 118 个全量测试 | OpenAPI、注册表、文档、部署契约、证据、Secret scan、数据库版本防护和 Phase 1B 审计 |
| 统一 Release 质量门 | 通过 | `artifacts/quality-gate/2026-08-27-agent-run-inspector-release.json`；21 项阻断检查全部通过 |
| Release 质量门 | 通过 | 后端 118 tests + 24 subtests，覆盖率 `86.15%`；前端与契约 Release Gate 通过 |

### 4.1 阈值解释

- `64%` 是防止存量覆盖率继续下降的 **CI ratchet**；
- `85%` 是企业发布总行覆盖率门槛，当前后端 Release 覆盖率为 `86.15%`；
- Harness、权限、资源隔离、证据验证、幂等和恢复等新增关键模块目标覆盖率为 `>=95%`；
- Ruff format 当前纳管既有受控内核模块以及 Agent Platform/Shadow API；mypy 纳管 20 个 source files。两者仍非全量后端，不得描述为存量债务已清零；
- Agent/Skills/MCP 已形成隔离 shadow runtime；Run Inspector API 已提供用户隔离、状态/Agent 筛选和稳定游标分页，但 Inspector UI、真实 PostgreSQL 多实例/恢复演练、durable worker、生产主链路和网络 MCP 部署仍未完成；
- 简历改写效果必须由事实性、JD 相关性、盲评、可读性和回归评测共同证明，不能只引用 ATS 分数。

## 5. 冻结与实施产物

- `quality/openapi-baseline.json`：98 项历史 OpenAPI 契约基线；
- `quality/openapi-approved-removals.json`：19 项产品表面删除审批；
- `quality/agent-registry.json`：5 个 shadow Agent 的 active 注册表；
- `quality/skills-registry.json`：4 个 shadow Skill 的 active 注册表；
- `quality/mcp-tool-registry.json`：2 个只读 MCP-compatible Tool 的 active 注册表；
- `backend/quality/baseline-manifest.json`：机器可读基线与活动快照；
- `scripts/run_quality_gate.py`：统一质量门及证据报告；
- `scripts/validate_*.py`：契约与注册表校验器；
- `scripts/run_secret_scan.py`：仓库密钥扫描器；
- `docs/adr/0002-product-surface-retirement.md`：Phase 1A 决策和兼容边界；
- `docs/MODULE_RETIREMENT_DEPENDENCIES.md`：Phase 1A/1B 退役依赖和迁移顺序；
- `docs/PHASE1B_DATA_CONTRACT_AUDIT.md`：只读数据审计、阻断规则和迁移准入；
- `backend/scripts/audit_phase1b_data_contract.py`：Phase 1B 机器可读审计报告生成器；
- `docs/OWNERS.md`：责任边界和审批要求。

## 6. 基线变更规则

1. 基线值只能由可复现命令或 CI Artifact 更新；
2. 降低阈值必须写 ADR、指定 owner、到期时间和恢复计划；
3. OpenAPI 删除只能按精确 Method + Path 批准，批准不得豁免其他契约变化；
4. 数据库破坏性变更必须采用 expand → migrate → contract；
5. 新增 Agent、Skill、MCP Tool 必须从 `planned` 迁移到 `active`，并提供真实 entrypoint、权限契约和测试；
6. 正式合并前重新执行 `--profile all --mode ci`，并把报告绑定到最终 commit；
7. 任何未执行项目必须明确写“未执行”，不得推断为通过。
