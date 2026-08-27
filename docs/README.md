# 项目文档索引

> 更新时间：2026-08-27

## 1. 当前权威文档

以下文档定义 Agent Platform v2 的开发方向，发生冲突时优先级从上到下：

1. [`AGENT_PLATFORM_DEVELOPMENT_SPEC.md`](./AGENT_PLATFORM_DEVELOPMENT_SPEC.md)
   产品边界、目标架构、Harness、MCP、Skills、多 Agent、安全、数据模型和开发计划。
2. [`QUALITY_GATE_STANDARD.md`](./QUALITY_GATE_STANDARD.md)
   企业级质量门、CI、测试、Agent Eval、安全、性能、发布和灰度标准。
3. [`RESUME_REWRITE_EVALUATION.md`](./RESUME_REWRITE_EVALUATION.md)
   简历改写真实性、证据、盲评、ATS、分层评测和发布阻断标准。
4. [`adr/0001-agent-platform-transition.md`](./adr/0001-agent-platform-transition.md)
   从固定 LLM 工作流迁移到 Agent Platform 的架构决策。
5. [`adr/0002-product-surface-retirement.md`](./adr/0002-product-surface-retirement.md)
   Phase 1A 产品表面退役、兼容窗口和回滚边界。
6. [`adr/0004-agent-shadow-runtime-and-production-boundary.md`](./adr/0004-agent-shadow-runtime-and-production-boundary.md)
   Agent shadow runtime 与生产边界。
7. [`adr/0005-agent-run-lifecycle-and-checkpoint-model.md`](./adr/0005-agent-run-lifecycle-and-checkpoint-model.md)
   Run 生命周期、幂等、并发和 Checkpoint。
8. [`adr/0006-mcp-tool-authorization-and-approval-policy.md`](./adr/0006-mcp-tool-authorization-and-approval-policy.md)
   MCP Tool 权限、审批和审计策略。
9. [`BASELINE_INVENTORY.md`](./BASELINE_INVENTORY.md)
   历史冻结基线、当前 API、数据库、测试、覆盖率和安全快照。
10. [`MODULE_RETIREMENT_DEPENDENCIES.md`](./MODULE_RETIREMENT_DEPENDENCIES.md)
   支付、组织、公司画像、运营后台和用户质量反馈的退役依赖与迁移顺序。
11. [`PHASE1B_DATA_CONTRACT_AUDIT.md`](./PHASE1B_DATA_CONTRACT_AUDIT.md)
   Phase 1B 只读数据审计、阻断规则和 expand/migrate/contract 准入。
12. [`AGENT_SHADOW_API.md`](./AGENT_SHADOW_API.md)
   Shadow API 的认证、功能开关、输入输出、错误脱敏、运行和生产晋级边界。
13. [`OWNERS.md`](./OWNERS.md)
   角色所有权、RACI、强制审批和事件响应责任。

## 2. 现有运行与部署文档

- [`LAUNCH_READINESS.md`](./LAUNCH_READINESS.md)：已按 Agent Platform v2 范围更新的发布准入与阻断清单。
- [`RELEASE_CHECKLIST.md`](./RELEASE_CHECKLIST.md)：现有发布操作清单；质量阈值以新质量门为准。
- [`DOCKER_DEPLOYMENT.md`](./DOCKER_DEPLOYMENT.md)：当前工作区中的 Docker 单机部署方案。
- [`OPERATIONS_RUNBOOK.md`](./OPERATIONS_RUNBOOK.md)：当前运维流程；已退役产品模块不再作为活动运维能力。
- [`SECURITY_BASELINE.md`](./SECURITY_BASELINE.md)：现有安全基线；Agent/MCP 新增要求以质量门为准。
- [`RAG_ARCHITECTURE.md`](./RAG_ARCHITECTURE.md)：当前 RAG 设计；后续作为 `knowledge-mcp` 的实现基础。
- [`FRONTEND_UI_SYSTEM.md`](./FRONTEND_UI_SYSTEM.md)：现有 UI 规范。

## 3. 历史和待更新文档

以下文档保留背景价值，但不能作为 Agent Platform v2 的最终验收依据：

- [`ENTERPRISE_ROADMAP.md`](./ENTERPRISE_ROADMAP.md)：已归档的旧 SaaS 企业化路线，不得作为 v2 验收依据。
- [`PRODUCT_STRATEGY.md`](./PRODUCT_STRATEGY.md)：已归档并由 Agent Platform v2 规范替代的旧商业化策略。
- [`KNOWN_ISSUES.md`](./KNOWN_ISSUES.md)：当前 P0/P1/P2 风险登记和已解决证据。
- 根目录 `面试简历Agent_需求文档.md`：最初 MVP PRD，作为历史需求来源保留。

## 4. 文档治理规则

- 每份权威文档必须包含版本、状态、日期和 owner；
- 架构决策必须写入 `docs/adr/`；
- Prompt、Skill、Agent、MCP Tool 和 Eval 必须版本化；
- 代码行为变化时，相关文档必须在同一 MR 更新；
- CI 检查结果必须生成机器可读 Artifact，文档不得手工声称未执行的检查通过；
- 过期文档必须明确标记“历史”或“已替代”，不得静默保留冲突说明；
- 文档链接、示例命令和配置名称应纳入自动检查。

- [ADR-0007：PostgreSQL Agent Run Store 与执行租约](./adr/0007-postgresql-agent-run-store-and-execution-lease.md)
