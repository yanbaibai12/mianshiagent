# 历史文档：旧 SaaS 企业化路线（已归档）

> 状态：Archived / Superseded
> 归档日期：2026-08-27
> 替代文档：[`AGENT_PLATFORM_DEVELOPMENT_SPEC.md`](./AGENT_PLATFORM_DEVELOPMENT_SPEC.md)、[`QUALITY_GATE_STANDARD.md`](./QUALITY_GATE_STANDARD.md)
> 使用限制：不得据此恢复 Billing、租户后台、套餐或运营后台。

## 归档决策

旧路线围绕租户、套餐、订单和机构后台展开。Agent Platform v2 采用模块化单体优先，并把企业级能力定义为可验证的运行治理，而不是 SaaS 功能数量。

## 当前企业化主线

1. **Agent Runtime**：Run/Step/Checkpoint/Trace、预算、超时、取消、重试、并发和幂等。
2. **Tool Governance**：MCP Registry、Agent allowlist、audience、风险分级、审批和工具侧用户归属校验。
3. **Skill Governance**：Skill SemVer、输入输出契约、事实安全约束、回归评测和回滚。
4. **Durability**：PostgreSQL Run Store、事务幂等、多实例锁、Redis/RQ durable worker 和恢复演练。
5. **AI Quality**：分层样本、Claim-level 金标准、独立事实验证器、人工双盲、胜率与 95% CI。
6. **Operations**：最小化 health/status/release-check/alerts/backup API，不建设业务运营后台。
7. **Security**：资源归属、数据最小化、审计、敏感输出脱敏、Prompt Injection 与跨用户攻击测试。

## 当前非目标

- 支付、订单、套餐、权益和价格管理；
- 组织/公司管理产品；
- 运营后台 UI；
- 通用质量反馈运营闭环；
- 在缺少真实数据和恢复证据时删除历史表；
- 将进程内 Shadow Runtime 宣称为生产 Agent 平台。

阶段计划和退出标准以当前开发规范为唯一准绳。
