# 安全基线

## 当前已落地

1. 数据隔离：简历、面试、报告接口均按当前用户过滤。
2. Token 过期：访问 token 包含 `iat` 和 `exp`。
3. 密码哈希：MVP 使用 PBKDF2-HMAC-SHA256，不存储明文密码。
4. CORS 白名单：不再默认 `*` 放开。
5. Trusted Host：限制 Host 头来源。
6. 安全响应头：`X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy`、`Permissions-Policy`、`Cache-Control`。
7. 请求 ID：每次响应返回 `X-Request-ID`，便于日志排查。
8. 限流：认证接口和普通 API 具备进程内限流。
9. 输入限制：简历、JD、作答内容设置长度上限。
10. 上传校验：PDF/DOCX 不只检查扩展名，还校验 PDF 文件头和 DOCX 内部结构。
11. 数据最小化：简历列表只返回摘要，详情页才返回原文和结构化数据。
12. 密钥保护：系统状态接口不返回 API Key。
13. 发布检查：`APP_ENV=production` 且 `ENFORCE_RELEASE_CHECKS=true` 时，默认密钥、SQLite、本地模型、localhost CORS、非 HTTPS、生产自动建表、LLM 静默兜底等 critical 项会阻止后端启动。
14. 系统状态保护：`/api/system/status` 和 `/api/system/release-checks` 需要登录后访问，避免公开暴露部署细节。
15. 商业化配置巡检：支付渠道、升级联系入口、价格和套餐额度会进入发布检查，避免收费入口配置错误。
16. Alembic 初始迁移：新环境可通过迁移脚本创建表结构，降低生产数据库手工建表风险。
17. 轻量管理员权限：通过 `ADMIN_EMAILS` 控制人工开通、用量汇总等运营接口，普通用户访问会返回 403。

## 生产上线前必须补齐

1. 使用成熟认证方案：JWT/opaque session、refresh token、退出黑名单。
2. 密码哈希升级：Argon2id 或 bcrypt，并支持历史哈希迁移。
3. HTTPS 强制：由网关或 Nginx 统一处理。
4. Redis 限流：替换进程内限流，支持多实例。
5. 审计日志：记录登录、上传、删除、导出、支付、管理员操作。
6. 数据加密：敏感字段加密存储，文件对象存储开启服务端加密。
7. 租户隔离：B 端版本必须按 tenant_id 做所有表级隔离。
8. 删除与导出：支持用户数据导出、账号注销、简历彻底删除。
9. LLM 数据策略：明确不将用户简历/JD/回答用于训练，关闭供应商训练保留。
10. Prompt 注入防护：对 JD、简历文本和用户回答做边界提示、输出校验和内容过滤。
11. 依赖扫描：引入 `pip-audit`、`npm audit` 或 CI 依赖扫描。当前前端 `npm audit` 为 0 漏洞；本地 Python 环境未安装 `pip-audit`，后端依赖审计需在 CI 或发布环境补跑。
12. 备份恢复：PostgreSQL 定期备份、恢复演练。
13. 管理后台权限：RBAC、二次确认、敏感操作审计。
14. 支付安全：订单回调验签、幂等处理、金额校验、订单状态机、退款审计。
15. 成本风控：记录每次 LLM 调用成本，按用户/IP/租户限制异常高频使用。
16. 隐私合规：上线前补齐隐私政策、用户协议、数据删除和数据导出流程。

## 数据分级

- 高敏：简历原文、JD、面试回答、报告、手机号、邮箱。
- 中敏：优化后的结构化简历、评分明细、薄弱点。
- 低敏：模板、系统配置、匿名统计。

## 运营安全策略

1. 默认不展示完整手机号和邮箱，除非用户进入简历详情。
2. 报告分享链接必须有过期时间和撤销能力。
3. 对批量上传、批量导出、异常高频调用做风控拦截。
4. LLM 调用失败时不把供应商原始错误直接暴露给用户。
5. 管理员只能查看必要字段，访问完整简历需审计。

## 发布安全闸

后端启动时会调用 `app.services.release_checks.assert_release_ready`。

生产发布必须通过：

1. `SECRET_KEY` 非默认且长度不少于 32。
2. `DEBUG=false`、`ENABLE_DOCS=false`。
3. 数据库使用 PostgreSQL。
4. 真实 LLM 已配置，不使用 local fallback。
5. CORS 和 Trusted Host 不包含 wildcard 或 localhost。
6. `PUBLIC_BASE_URL` 使用 HTTPS。
7. 套餐价格和额度配置合法。

本地演示可以保留 warning，但商业发布不应保留 critical。
