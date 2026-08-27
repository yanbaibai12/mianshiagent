# Phase 1B 历史数据契约审计与迁移准入

> 文档版本：1.0.0
> 状态：审计基础已实现；数据迁移和 contract migration 未开始
> 编制日期：2026-08-27
> Owner：Agent Platform Team
> 关联决策：[`adr/0002-product-surface-retirement.md`](./adr/0002-product-surface-retirement.md)

## 1. 目标

Phase 1B 将迁移期的“个人组织兼容模型”收缩为明确的个人用户所有权契约，并分类处理已经退役的组织、支付、质量反馈和公司画像历史数据。

本阶段必须遵循 **expand → migrate → contract**。当前只完成了只读审计基础，尚未创建删表、删列、外键收缩或数据改写迁移。

## 2. 已实现的审计基础

代码：

- `backend/app/services/data_contract_audit.py`：生成确定性的只读迁移准入报告；
- `backend/scripts/audit_phase1b_data_contract.py`：数据库 Schema 校验、报告落盘、证据哈希和阻断退出码；
- `backend/tests/test_phase1b_data_audit.py`：正常数据、孤儿记录、自引用外键、跨用户归属、共享组织、公司画像归属、凭据脱敏、PostgreSQL 方言编译和缺失 Schema 回归。

审计覆盖：

1. 26 张 SQLAlchemy 业务表的 row count；
2. 所有已声明外键的孤儿记录；
3. 带 `user_id + organization_id` 业务资产与有效成员关系的一致性；
4. 用户是否恰好对应一个有效组织；
5. 组织是否能唯一映射到一个有效成员和一个有效 owner；
6. 公司画像是否能唯一映射到个人用户；
7. 简历、版本、任务、岗位、面试、训练计划、质量候选等父子实体的所有权一致性；
8. 退役表的历史数据量：`billing_accounts`、`payment_orders`、`quality_annotations`、`quality_eval_candidates`、`company_interview_profiles`。

## 3. 执行方式

必须先对目标数据库完成备份，并使用与生产相同版本的 PostgreSQL 只读副本或受控 staging 数据库执行：

```powershell
cd backend
.\.venv-codex\Scripts\python.exe scripts\audit_phase1b_data_contract.py `
  --database-url "postgresql+asyncpg://<readonly-user>@<host>/<database>" `
  --report artifacts\data-contract\phase1b-postgresql-audit.json
```

安全要求：

- 审计账号只授予 `CONNECT`、`USAGE` 和所需表的 `SELECT`；
- 禁止使用数据库超级用户；
- 报告不得包含数据库 URL、邮件、简历正文、支付原始载荷或用户输入，只记录数量和规则标识；失败证据会脱敏原始及 SQLAlchemy 渲染后的数据库 URL；
- 默认发现 blocker 时退出码为 `1`；Schema 缺失或读取失败时退出码为 `2`；
- `--report-only` 仅用于探索性盘点，不能作为迁移准入证据；
- 报告必须与数据库快照标识、Alembic revision、Git commit 和执行人一起归档。

## 4. 阻断规则

| Blocker | 含义 | 处理要求 |
|---|---|---|
| `foreign-key-orphans` | 外键指向不存在的父记录 | 修复、隔离或形成经批准的归档清单 |
| `organization-membership-mismatches` | 用户资产的组织不属于该用户 | 按原始审计证据确认真实 owner，禁止猜测 |
| `users-without-single-active-organization` | 用户没有或拥有多个有效组织 | 建立唯一个人 owner 映射 |
| `organizations-without-single-active-member` | 组织不能唯一映射到个人用户 | 拆分、归档或人工批准处置 |
| `organizations-without-single-active-owner` | 组织 owner 缺失或不唯一 | 修复 owner 决策和审计记录 |
| `company-profile-owner-ambiguity` | 历史画像无法唯一归属 | 合规归档或生成脱敏离线样本，禁止静默迁移 |
| `cross-entity-owner-mismatches` | 父子业务实体 owner 不一致 | 修复跨用户/跨组织引用后重跑审计 |

任何 blocker 数量大于 0 时，禁止执行 contract migration。

## 5. 后续迁移切片

### 5.1 Expand

- 为需要直接个人所有权的表增加可空 `owner_user_id` 或兼容视图；
- 增加索引和双写校验，但不删除 `organization_id`；
- 新增按 user ownership 的读取路径，保留回滚开关；
- 为账号导出、账号删除和跨用户授权增加双模型回归。

### 5.2 Migrate

- 在冻结快照上生成迁移映射；
- 分批回填 owner，每批记录输入数量、成功数、跳过数和失败原因；
- 对退役支付/质量/画像数据执行保留、导出、匿名化或删除分类；
- 每批完成后复跑本审计、账号导出和跨用户访问测试；
- PostgreSQL 环境执行升级、降级和备份恢复演练。

### 5.3 Contract

只有以下证据齐全后才能创建删除旧列/表的 Alembic 迁移：

- blocker 为 0；
- 迁移前后 row count 和 owner count 一致；
- 无孤儿记录、无跨用户引用；
- 账号导出和删除结果正确；
- PostgreSQL 恢复演练通过；
- 独立 ADR 已批准；
- Release Gate 达到 85%，且 contract migration 与 Harness 核心不在同一原子提交。

## 6. 当前限制

截至 2026-08-27：

- 只在自动化测试中使用 SQLite 验证了审计逻辑；
- 尚未对真实 PostgreSQL 数据副本执行审计；
- 尚未生成实际历史数据分类报告；
- 尚未创建 expand、migrate 或 contract Alembic revision；
- 后端 Release Gate 仍因总行覆盖率低于 85% 阻断；
- Harness、MCP、Skills 和多 Agent 已有隔离 shadow runtime，但 Phase 1B PostgreSQL 演练完成前不得接管生产持久化主链路。

因此，本文件和审计脚本只能证明“迁移准入机制已开始建设”，不能证明 Phase 1B 数据迁移已经完成。
