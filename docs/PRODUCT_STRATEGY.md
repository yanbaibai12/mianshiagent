# 历史文档：旧商业化方案（已归档）

> 状态：Archived / Superseded
> 归档日期：2026-08-27
> 替代文档：[`AGENT_PLATFORM_DEVELOPMENT_SPEC.md`](./AGENT_PLATFORM_DEVELOPMENT_SPEC.md)、[`adr/0001-agent-platform-transition.md`](./adr/0001-agent-platform-transition.md)、[`adr/0002-product-surface-retirement.md`](./adr/0002-product-surface-retirement.md)
> 使用限制：不得作为当前产品路线、接口设计、环境变量或发布要求。

## 归档原因

旧方案以 SaaS 套餐、支付、组织管理和运营转化为主线，已经与 Agent Platform v2 的产品边界冲突。当前版本聚焦：

- Harness 与受控 Run 生命周期；
- MCP-compatible Tool Gateway；
- 版本化 Skills；
- 多 Agent 编排与可观测性；
- 基于 Claim/Evidence 的真实简历改写；
- 面试训练、评测与恢复能力。

支付、套餐、订单、权益、组织/公司管理、运营后台和面向用户的质量反馈产品表面已按 ADR-0002 退役。历史表仅为 Phase 1B 数据迁移兼容保留，不代表活动产品能力。

## 当前产品成功标准

当前阶段不以付费转化、套餐 ARPU 或订单金额作为工程完成标准。必须优先证明：

1. 简历改写不引入无证据事实；
2. Agent Run 可审计、可取消、可重试并受预算约束；
3. Tool 调用满足最小权限、用户归属和输入输出契约；
4. 多 Agent 相比固定工作流具有可测量的质量收益；
5. Release Gate、数据迁移和人工盲评证据真实可复现。

旧商业化内容可通过 Git 历史查阅；任何重新引入商业化能力的提案必须新建 ADR、威胁模型、数据契约和独立发布门。
