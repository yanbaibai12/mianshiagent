# 发布就绪清单

> 文档版本：2.1.0
> 更新日期：2026-08-27
> 当前结论：工程 Release Gate 已通过；商业生产发布仍未获批准。

## 1. 发布级别

项目只允许以下两种清晰区分的发布级别：

1. **本地/内部演示**：SQLite、local LLM、进程内 Agent shadow runtime。不得处理真实生产数据，不得承诺高可用或简历效果提升。
2. **生产发布**：PostgreSQL、真实 LLM、Redis/RQ、外部 Qdrant、HTTPS、持久化 Agent Run Store、真实 MCP/domain adapter 和完整发布证据。

当前只满足内部演示和工程候选标准，不满足生产发布标准。

## 2. 已通过的工程门（2026-08-27）

- 后端 Release Gate：116 tests + 19 subtests，覆盖率 `86.03%`；Ruff、受控 format、mypy、pip-audit、Alembic heads 全部通过；
- 前端 Release Gate：lint、7 个单测及覆盖率、typecheck、build、npm high audit 全部通过；
- 契约与安全 Release Gate：文档、部署运行时/生产开关、OpenAPI、Agent、MCP、Skills、Secret Scan、Agent safety eval 全部通过；
- Chromium E2E：3/3 核心场景通过；
- Agent shadow runtime：5 Agents、4 Skills、2 个只读 MCP-compatible Tools；
- Agent fact-safety 自动评测：8/8 通过。

证据：

- `artifacts/quality-gate/2026-08-27-backend-release-agent-platform.json`；
- `artifacts/quality-gate/2026-08-27-contracts-release-agent-platform.json`；
- `artifacts/quality-gate/2026-08-27-frontend-release.json`；
- `artifacts/evaluation/agent-shadow-safety.json`。

## 3. 生产发布阻断项

以下任一项未完成，生产发布必须失败关闭：

### 3.1 数据与恢复

- 在生产等价 PostgreSQL 环境完成 Alembic upgrade、rollback/restore 和备份恢复演练；
- Phase 1B row count、孤儿记录、owner 映射、账号导出/删除核对全部通过；
- ADR-0003 从 `Proposed` 经 Data/Security/Service Owner 批准；
- Alembic `0018` 的 Agent Run/Step/Trace/Checkpoint Store 在真实 PostgreSQL 上完成升级、降级、并发和恢复验证；
- 多实例下事务幂等、执行租约、租约过期接管和取消竞争经过真实数据库验证；
- Agent durable worker 完成重复投递、强制终止和重启恢复演练。

### 3.2 Agent 与 MCP

- shadow runtime 通过显式 feature flag 灰度，不直接替换稳定主链路；
- `resume.read`、`interview.questions.read` 接入真实领域服务，并验证 user ownership、audience、审计和 PII 脱敏；
- 若采用网络 MCP Server，必须完成身份认证、传输安全、schema negotiation、超时、重试和审计演练；
- 写工具默认不存在；新增写工具必须高风险分级、显式审批、幂等键和补偿/回滚；
- Run、Step、Tool、Skill、handoff、模型和版本信息进入可查询 Trace。

### 3.3 简历真实效果

- 至少 120 条经过授权、脱敏、分层的简历/JD 样本；
- Claim-level Evidence Graph 和独立事实验证器；
- 原文与改写结果的双盲人工评测；
- 报告胜率、95% 置信区间、岗位/年限/语言分层和群体退化；
- unsupported claim、PII 串用、跨用户证据引用均为 0；
- 自动 ATS 或 Agent 自评分不得单独作为效果证明。

### 3.4 安全与运维

- `APP_ENV=production`、`DEBUG=false`、`AUTO_CREATE_DB=false`；
- PostgreSQL、Redis/RQ、外部 Qdrant 和真实 LLM Provider；
- HTTPS、受限 CORS/Trusted Hosts、正式密钥管理与轮换；
- Redis/网关级限流，不使用单进程内存限流作为生产控制；
- 外部告警、SLO、错误率、模型失败率、队列积压、成本和恢复告警；
- 日志和 Trace 不记录完整简历、联系方式、Token、密钥或未经脱敏的回答。

## 4. 已退役能力不得回流

生产清单不再要求、也不得重新引入以下产品面：

- 支付、套餐、价格、升级、订单和人工开通；
- 组织/公司管理 UI 与公开 API；
- 公司画像 CRUD；
- 运营后台 UI；
- 面向用户的在线质量反馈运营闭环。

如未来确需恢复，必须新建 ADR、威胁模型、数据契约和独立质量门，不能以“上线需要”为理由绕过产品范围决策。

## 5. 发布流程

1. 冻结 release candidate 的 Git SHA、依赖锁、模型、Prompt、Skill、Tool 和评测集版本；
2. 在目标 PostgreSQL 环境完成迁移、备份和恢复演练；
3. 执行 `scripts/run_quality_gate.py --profile all --mode release`；
4. 执行 Chromium E2E、Agent Eval、简历事实性与人工盲评；
5. 由 Service Owner、Security Owner、Data Owner 审核证据清单；
6. 小流量灰度，监控 SLO、错误、成本、事实性和跨用户隔离；
7. 任一不可豁免指标失败立即停止扩量或回滚。

## 6. 当前批准结论

- **内部演示：允许**，前提是不使用真实生产数据并明确 shadow runtime 边界；
- **工程合并候选：质量门通过**，仍需代码评审和最终 CI 绑定 commit；
- **商业生产发布：不批准**，阻断原因为真实 PostgreSQL/Agent Store 演练、durable worker、生产 Tool 服务边界和简历人工效果证据尚未完成。
