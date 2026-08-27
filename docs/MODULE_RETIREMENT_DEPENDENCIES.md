# Phase 1 模块退役依赖与迁移方案

> 文档版本：1.3.0
> 状态：Phase 1A 已实施；Phase 1B 只读审计基础已实现，数据迁移待实施
> 编制日期：2026-08-27
> Owner：Agent Platform Team
> 关联 ADR：[`adr/0001-agent-platform-transition.md`](./adr/0001-agent-platform-transition.md)、[`adr/0002-product-surface-retirement.md`](./adr/0002-product-surface-retirement.md)

## 1. 目标与原则

Phase 1 退役支付/商业套餐、组织管理、公司画像 CRUD、运营后台 UI 和面向用户的质量反馈闭环，同时保留简历、岗位、面试、报告、训练计划、账号治理和平台运维能力。

强制原则：

1. **先断依赖，再删接口，再迁数据，最后删表**；
2. 数据库采用 expand → migrate → contract，不在一个不可逆迁移中直接删表；
3. 删除用户能力前先提供必要的数据导出、备份和回滚点；
4. API 删除必须更新 OpenAPI 基线，并明确是已批准的产品范围变更；
5. 运营 UI 退役不等于删除 health、metrics、release check、审计和备份能力；
6. 在线质量反馈退役不等于删除 Agent Eval、简历事实验证和离线质量门；
7. 每个切片独立通过测试和 E2E，禁止一次性“大爆炸”删除。

## 2. Phase 1A 实施状态（2026-08-27）

| 切片 | 状态 | 实施证据 |
|---|---|---|
| 前端导航、路由、页面和服务退役 | 已完成 | 删除 3 个页面、5 个前端服务；活动 TS/TSX 36 个、页面 12 个 |
| 商业 entitlement 解耦 | 已完成 | 核心 Router 不再 import 商业服务；`usage_telemetry` 仅记录事实 |
| 公开 API Router 退役 | 已完成 | 活动 Router 12 个；19 个批准 operation 从 OpenAPI 消失 |
| 历史公司画像兼容 | 已完成 | 保留内部 snapshot 匹配；private、opt-out、PII 不进入 snapshot |
| 运维能力保留 | 已完成 | health、status、release check、alerts、backup、knowledge import 保留并回归 |
| 在线质量反馈产品表面退役 | 已完成 | `/api/quality/*` 与前端反馈入口删除；E2E 验证入口不存在 |
| 数据库 expand/migrate/contract | 审计基础已实现 | 当前 29 张表、Alembic head `0018`：26 张历史业务表仍处兼容窗口，3 张为 Agent Runtime；Phase 1B 只读审计覆盖历史业务 row count、孤儿记录和 owner 映射，尚未执行历史数据 contract migration |
| Harness/MCP/Skills/多 Agent | shadow runtime 与持久化 Store 代码已完成 | 5 Agents、4 Skills、2 个真实数据库只读 MCP-compatible Tools；PostgreSQL Store/事务幂等/租约已实现，但仅 Shadow API 可用，未完成真实 PostgreSQL 多实例演练、durable worker 和生产主链路接入 |

Phase 1A 的实施边界以 ADR-0002 为准。下文保留完整依赖图，用于 Phase 1B 数据契约迁移和回滚设计；其中已经删除的代码路径属于历史依赖证据，不代表文件仍存在。

## 3. 风险分级

| 模块 | 风险 | 原因 |
|---|---|---|
| 支付/商业化 | 中 | 与简历创建、额度、账号导出和 usage 记录耦合 |
| 公司画像 CRUD | 高 | 面试生成、评分、报告和训练计划仍引用 snapshot/profile id |
| 组织/租户 | 极高 | 多数业务表持有 `organization_id`，训练计划存在非空外键 |
| 运营后台 | 中高 | 同一 Router 混合运营功能与生产运维能力 |
| 用户质量反馈 | 中高 | 数据被在线审核流程、账号导出和质量候选逻辑引用 |

## 4. 支付与商业化

### 4.1 代码依赖

- 后端：`app/routers/payments.py`、`app/services/payments.py`；
- 商业权益：`app/routers/business.py`、`app/services/business.py`；
- 前端：`src/services/payments.ts`、`src/services/business.ts`、`src/pages/ResumeList.tsx`；
- 账号导出：`app/routers/account.py` 中 `billing_account`、`payment_orders`；
- 配置：`BILLING_ENABLED`、`PAYMENT_*`、`FREE_*_QUOTA`、`PRO_*_QUOTA`、价格字段。

### 4.2 数据依赖

- `billing_accounts`；
- `payment_orders`；
- `usage_records` 中套餐、额度和商业事件语义；
- `users`、`organizations` 与支付记录的关系。

### 4.3 迁移顺序

1. 将核心功能授权改为产品能力开关/固定个人版策略，不再读取 entitlement；
2. 移除 `ResumeList` 的套餐价格、checkout、upgrade request、剩余额度和 paywall；
3. 删除 `/api/payments/*` 和 `/api/business/entitlements|upgrade-request|admin/*` 调用方；
4. 更新账号导出 Schema，必要时保留一次性历史账单导出；
5. 停写商业 usage 事件并验证核心 usage/审计用途；
6. 在一个版本中保留只读历史数据，再通过独立 Alembic contract migration 删除表/列；
7. 清理配置、文档、测试和 OpenAPI 基线。

### 4.4 验收

- 新用户无需套餐即可完成简历、JD、面试、报告和训练计划；
- 前端无价格、额度、支付、升级入口；
- 核心接口不再 import 商业服务；
- 历史数据导出与删除策略已验证；
- 重复请求不会因移除额度扣减而改变幂等语义。

## 5. 组织管理与租户

### 5.1 代码依赖

- 后端：`app/routers/organizations.py`、`app/services/tenancy.py`；
- 前端：`OrganizationSettings.tsx`、`services/organizations.ts`、`/organizations` 路由和导航；
- 账号导出/删除：组织、成员与关联对象；
- 多数领域服务通过 `organization_id` 过滤、创建或授权。

### 5.2 数据依赖

直接涉及：

- `organizations`；
- `organization_members`；
- `billing_accounts`、`payment_orders`；
- `resumes`、`resume_versions`、`async_tasks`、`job_applications`、`interviews`、`usage_records`、`knowledge_documents`、`company_interview_profiles`、`training_plans`、`quality_*`、`alert_notifications`、`audit_logs` 等表中的 `organization_id`。

特别风险：`training_plans.organization_id` 当前为非空并使用级联外键，不能直接删除组织记录。

### 5.3 目标所有权模型

Phase 1 回归 **个人用户所有权**：

- 所有用户资产的授权主键为 `user_id`；
- 不再暴露组织创建、邀请、成员和切换能力；
- 若为兼容迁移临时保留 personal organization，只能作为内部实现，不得继续作为产品概念；
- Agent/MCP 的资源 audience 必须使用 `user_id`，不得依赖已退役组织 UI。

### 5.4 Expand/Migrate/Contract

**Expand**

- 为缺少 `user_id` 的用户资产补充 owner 字段或建立可验证映射；
- 新读写路径优先使用 `user_id`；
- 增加双读一致性检查和孤儿数据检测。

**Migrate**

- 将 personal organization 的所有资产映射到 owner user；
- 对多人组织、无 owner、重复映射和孤儿数据生成阻断报告；
- 迁移脚本必须可重复执行并输出数量校验。

**Contract**

- 删除组织 UI/API；
- 停止写入 `organization_id`；
- 在至少一个稳定版本后删除外键、列和组织表；
- 删除 tenancy service 前确认所有授权测试改为 user ownership。

### 5.5 验收

- 任一用户只能访问自己的资源；
- 迁移前后每类资产数量一致；
- 账号导出和删除不遗留孤儿记录；
- 跨用户访问测试全部返回拒绝；
- PostgreSQL 升级、降级/恢复和备份恢复演练通过。

## 6. 公司画像 CRUD

### 6.1 代码依赖

- 后端：`app/routers/company_profiles.py`、`app/services/company_profiles.py`；
- 前端：`CompanyProfiles.tsx`、`services/companyProfiles.ts`、`/company-profiles`；
- 面试：`company_profile_id`、`company_profile_snapshot`、生成/评分/报告上下文；
- 训练计划：`related_company_profile_id`、公司名称归一化与 snapshot；
- 导出：面试报告中的公司画像摘要。

### 6.2 决策

- 退役用户可管理的公司画像实体和 CRUD；
- 有价值且来源合规的数据先脱敏导出为离线知识/Eval 数据；
- 未来若需要公司/岗位知识，由 `knowledge-mcp` 或版本化 Skill 提供，只读、可追踪且不恢复 CRUD；
- 旧面试历史可保留 snapshot 用于回放，但新 Run 不再依赖可变 profile id。

### 6.3 迁移顺序

1. 禁止新建/更新画像，保留只读窗口；
2. 面试创建改为不读取 profile CRUD，模板中的 `use_company_profile` 默认关闭；
3. 报告和训练计划兼容历史 snapshot，不要求 profile 实体存在；
4. 导出合规知识/Eval 数据并记录来源、许可和脱敏状态；
5. 删除前端页面/API；
6. 清理外键后删除 `company_interview_profiles`。

## 7. 运营后台

### 7.1 必须删除

- `SystemAdmin.tsx` 和 `/admin/system`；
- 商业 usage summary、grant plan；
- 在线质量候选审核 UI/API；
- 面向运营的手工 reindex、手工 backup 等公开管理入口（若保留必须转为受控运维命令）。

### 7.2 必须保留或替代

- `/health`；
- 生产状态、metrics、release checks 和告警所需的机器接口；
- 审计日志；
- 自动备份、恢复、reindex 的受控运维流程；
- CI/CD 和 Runbook 中可验证的发布检查。

`app/routers/system.py` 需要逐 operation 分类，不得整文件删除。管理接口应迁移到最小权限的内部运维边界，默认不向普通应用会话暴露。

## 8. 面向用户的质量反馈

### 8.1 退役范围

- `/api/quality/annotations` 用户提交与查询；
- `/api/quality/admin/*` 在线候选审核；
- `quality_annotations`、`quality_eval_candidates` 在线运营状态机；
- 前端 `services/quality.ts` 及相关评分/标签入口。

### 8.2 保留范围

- 简历 Claim/Evidence 事实验证；
- Agent routing/tool/handoff eval；
- ATS、盲评和离线回归集；
- 安全、隐私和输出质量门；
- 脱敏、授权且可追踪的离线样本。

### 8.3 迁移顺序

1. 冻结新 annotation 写入；
2. 对历史样本执行授权、脱敏、去重和用途审查；
3. 仅将合格样本导出到版本化离线 eval；
4. 从账号导出和删除流程中移除在线实体并验证历史数据处理；
5. 删除 UI/API 和表；
6. 将 Eval Registry 与产品数据库解耦。

## 9. 推荐执行切片

| 切片 | 内容 | 前置条件 | 回滚点 |
|---|---|---|---|
| 1 | 移除前端导航和纯 UI 入口 | 无 | 恢复路由/导航 |
| 2 | 解除支付/权益对核心链路阻断 | 核心功能回归测试 | 恢复 entitlement adapter |
| 3 | 停止公司画像新写入并移除新链路依赖 | 历史 snapshot 兼容 | 重新开启 feature flag |
| 4 | 用户 ownership expand migration | 数据审计报告 | 数据库备份/降级脚本 |
| 5 | 移除旧 API Router | 调用方为 0、OpenAPI 变更审批 | 恢复 Router |
| 6 | 离线导出质量/画像数据 | 合规与脱敏批准 | 保留只读源表 |
| 7 | Contract migration 删除列/表 | 至少一个稳定版本、恢复演练 | 数据库快照恢复 |

## 10. 每个切片的阻断检查

- `python scripts/run_quality_gate.py --profile all --mode ci`；
- 更新后的核心 Playwright E2E；
- OpenAPI 删除清单与批准记录；
- `audit_phase1b_data_contract.py` 的 row count、孤儿记录、owner 映射和阻断报告；
- 数据迁移前后 row count、孤儿记录、重复映射报告；
- 账号导出/删除回归；
- 跨用户授权测试；
- `git diff --check` 与完整 diff 审查；
- 生产发布前 `--mode release`，不得以 CI ratchet 替代发布门。

## 11. 明确禁止

- 在同一个迁移中删除组织表及所有外键；
- 用前端隐藏代替后端权限/接口退役；
- 为追求绿灯删除失败测试或下调质量阈值；
- 未脱敏直接把用户反馈转成 Eval；
- 删除 `system.py` 后失去 health、release check 或恢复能力；
- 把公司画像 CRUD 换名后继续作为隐藏产品模块；
- 在没有数量校验和备份恢复证据时执行不可逆数据删除。
