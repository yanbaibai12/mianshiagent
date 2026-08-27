# ADR-0002：Phase 1A 产品表面退役与兼容边界

- 状态：Accepted
- 决策日期：2026-08-27
- 决策者：项目维护者
- 影响范围：前端路由与导航、FastAPI Router、OpenAPI 契约、商业权限、历史数据兼容、测试和发布流程
- 关联决策：ADR-0001

## 背景

Agent Platform v2 已明确不再建设支付、套餐、组织管理、公司画像 CRUD、运营后台 UI 和面向用户的质量反馈闭环。现有实现同时存在前端入口、公开 API、商业额度阻断和历史数据外键。如果一次性删除表与外键，会破坏账号导出、训练计划、面试历史快照和数据可恢复性；如果只隐藏前端，则公开 API 和商业阻断仍然存在，不能视为完成退役。

## 决策

Phase 1A 采用“**先退役产品表面和运行时依赖，后迁移数据契约**”的非破坏性方案：

1. 删除支付、商业权益、组织管理、公司画像管理、运营后台和用户质量反馈的前端页面、服务与路由；
2. FastAPI 不再注册 `/api/payments/*`、`/api/business/*`、`/api/organizations/*`、`/api/company-profiles/*`、`/api/quality/*`；
3. 核心简历、JD、面试和报告流程不得调用商业 entitlement，也不得返回 402 套餐额度阻断；
4. 运行统计迁移到独立的 operational usage telemetry 边界，它只记录事实，不执行套餐判断；
5. 暂时保留组织、支付、质量和公司画像相关表及历史数据，继续支持账号导出、审计、训练计划外键与历史面试快照；
6. personal organization 在迁移期继续作为内部数据隔离兼容实现，但不作为用户可管理的产品能力；
7. `system` 中的 health、status、release check、alert 和 backup API 继续保留，但删除运营后台 UI；
8. OpenAPI 删除必须逐项登记在 `quality/openapi-approved-removals.json`，未登记删除继续阻断质量门。

## OpenAPI 破坏性变更治理

批准清单必须满足：

- 精确到 HTTP Method 与 Path，不允许通配符；
- 每项必须存在于冻结基线且确实已从当前 Schema 删除；
- 必须提供 owner、原因和本 ADR；
- 批准仅豁免 `operation_removed`，不能豁免请求、响应、安全或参数契约变化；
- 清单无效、重复、越界、ADR 缺失或登记项尚未删除时，兼容检查必须失败；
- 报告必须把批准删除与未批准 breaking changes 分栏展示，禁止伪装成“无变更”。

## 不在本阶段执行

- 删除数据库表、列或外键；
- 清空历史支付、组织、公司画像或质量数据；
- 删除账号导出中的历史兼容字段；
- 引入 Agent Harness、MCP Runtime 或多 Agent 核心模型；
- 将旧模块删除与 Harness 核心实现混入同一原子提交。

## 后续迁移

后续采用 expand → migrate → contract：

1. 为个人模式补齐新的资源归属字段或兼容视图；
2. 迁移并核对历史记录数量、孤儿记录和导出结果；
3. 验证备份恢复与回滚路径；
4. 在独立 ADR 和独立迁移中删除旧表、列和外键；
5. 消费并归档 OpenAPI 删除批准清单，建立新的 v2 契约基线。

## 验收标准

- 退役前端路径不可达且不再进入生产 bundle；
- 19 个退役 API operation 返回 404，并从当前 OpenAPI Schema 消失；
- 核心简历上传、优化、JD 适配、面试创建和报告导出不依赖套餐权益；
- 历史公司画像快照仍可用于既有面试上下文；
- OpenAPI 校验报告明确显示 19 项批准删除且未批准 breaking changes 为 0；
- CI 质量门真实通过；Release Gate 仍按 85% 覆盖率独立阻断，不得降级阈值。

## 结果

### 正面

- 产品边界与 Agent Platform v2 定位一致；
- 核心流程不再被支付或套餐状态阻断；
- 公开攻击面和前端无效入口减少；
- 历史数据和回滚能力得到保留；
- API 破坏性变更具备机器可读审批证据。

### 负面

- 数据库仍保留一段时间的 legacy 表和字段；
- 账号导出仍包含历史兼容数据；
- 历史 OpenAPI 基线保持 98 项，当前运行时 Schema 为 79 项，并依赖 19 项精确批准清单解释差异；
- contract migration 完成前仍需维护 personal organization 内部兼容逻辑。


## 实施证据（2026-08-27）

- 活动 Router：12 个；Router 装饰器：78 个；
- 历史 OpenAPI：98 operations；当前 OpenAPI：79 operations；批准删除：19；未批准 breaking changes：0；
- 后端：40 passed、19 subtests passed，CI 覆盖率 64.05%；
- 前端：lint、7 个单元测试、typecheck、build、3 个 Chromium E2E 场景通过；
- 数据库：26 张表、Alembic head `0017`，未执行破坏性迁移；
- Release Gate：测试通过但 `64.05% < 85%`，按策略保持阻断；
- Harness、MCP、Skills、多 Agent：未在本 ADR 中实现。
