# 安全基线

> 状态：Active
> 更新日期：2026-08-27
> Owner：Security Owner / Agent Platform Team

## 1. 当前已落地

1. 简历、面试、报告和 Shadow Run 按当前用户隔离。
2. 访问 Token 包含签发和过期时间，密码不以明文保存。
3. CORS、Trusted Host、安全响应头、Request ID 和输入长度限制已启用。
4. PDF/DOCX 同时校验扩展名与文件结构。
5. 简历列表执行数据最小化，系统状态不返回 API Key。
6. 生产 Release Check 对默认密钥、SQLite、本地模型、localhost、非 HTTPS、自动建表和静默 fallback 失败关闭。
7. Alembic revision guard 要求生产数据库处于唯一代码 head。
8. 依赖审计、Secret Scan 和 OpenAPI Contract 已进入统一质量门。
9. MCP Gateway 校验 Tool 存在性、Agent 双向 allowlist、audience、审批、输入输出契约和超时。
10. 真实 Resume/Interview Shadow adapter 在数据库查询中再次校验 `user_id`。
11. Shadow API 默认关闭、隐藏 OpenAPI、要求认证和 Idempotency-Key。
12. Shadow 响应移除内部 state、完整 Tool Result、指纹、幂等键和内部异常类。
13. 简历 Evidence Skill 排除联系方式，改写只接受 source-exact 且 SHA-256 有效的 Claim。
14. 支付、组织/公司管理、运营后台和面向用户的质量反馈产品表面已退役。
15. PostgreSQL Agent Run Store、事务幂等、持久化 Step/Trace/Checkpoint、执行租约、取消竞争和失败重试代码已实现；数据库错误默认失败关闭。

## 2. 生产上线前必须补齐

1. 成熟认证与会话：短 access token、refresh rotation、revocation 和异常登录检测。
2. Argon2id 或合规密码哈希迁移。
3. 网关 HTTPS、WAF/限流和 Redis 分布式限流。
4. PostgreSQL 字段/备份加密、PITR 和真实恢复演练。
5. LLM 数据保留、训练使用、区域和供应商合同策略。
6. Prompt Injection、间接注入、Tool 参数污染和输出 Schema 对抗测试。
7. 在真实 PostgreSQL 上验证 Agent Run Store 的事务幂等、行锁/租约接管、取消竞争、多实例并发、升级/降级和恢复；SQLite 合同测试与 PostgreSQL SQL 编译不得作为替代证据。
8. durable worker 的 kill/restart、重复投递和取消延迟演练。
9. 网络 MCP Transport 的认证、授权、Schema negotiation 和审计。
10. Run Inspector 的字段级授权与脱敏测试。
11. 隐私政策、用户协议、数据导出和删除闭环。
12. 简历改写人工双盲、事实金标准和群体退化检查。

## 3. 数据分级

- **高敏**：简历原文、JD、面试回答、报告、手机号、邮箱、Token、Tool 原始结果。
- **中敏**：优化后的结构化简历、评分明细、Evidence Claim、薄弱点、Run output。
- **低敏**：模板、公开题库、无用户输入的系统配置和聚合指标。

高敏数据不得进入 Trace、日志、通用错误、Issue、MR 描述或质量 Artifact。

## 4. Agent / MCP 安全策略

1. Prompt 或 Agent 名称不是授权边界；Tool 必须执行代码级授权。
2. audience 必须等于 Run user，数据库资源必须再次匹配 owner。
3. 所有写 Tool、高风险 Tool 和审批型 Tool 默认拒绝，未经批准成功率必须为 0。
4. Tool 输出不得整体复制到 Trace/Checkpoint 公共响应。
5. 跨用户资源和不存在资源使用相同公共错误形态，防止资源枚举。
6. Retry 必须有次数上限，不能绕过预算、审批或幂等。
7. 同一 Run 并发执行必须串行化；代码已实现 PostgreSQL 事务 claim 与 execution lease，但生产前必须完成真实多实例、租约过期接管和 stale owner 拒绝演练。
8. 同步 Tool 超时不等于线程已终止，生产 adapter 必须使用可取消 I/O 或进程隔离。
9. 事实安全自动评测只证明不变量，不证明招聘效果。

## 5. 发布安全闸

生产必须满足：

1. 非默认 `SECRET_KEY` 且长度不少于 32；
2. `DEBUG=false`、`ENABLE_DOCS=false`、`AUTO_CREATE_DB=false`；
3. PostgreSQL、真实 LLM/Embedding、正式 HTTPS 域名；
4. Redis/RQ 且关闭 local fallback；
5. backup/alert/metrics 配置和恢复证据；
6. `AGENT_SHADOW_API_ENABLED=false` 且 `AGENT_RUN_STORE_BACKEND=postgresql`；
7. Backend、Contracts、Frontend Release Gate 和 E2E 通过；
8. 无 high/critical 依赖漏洞、Secret finding 和未批准 OpenAPI breaking change。

本地 warning 不得被解释为生产可接受。任何 critical 都必须阻止启动或发布。

## 6. 退役历史数据边界

数据库中的组织、支付、质量和公司画像历史表仅为 Phase 1B 迁移兼容保留。删除、匿名化或保留必须基于真实 PostgreSQL 审计、保留策略和双人审批，不得因产品入口已删除而直接清表。
