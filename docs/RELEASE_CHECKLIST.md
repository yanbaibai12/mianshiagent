# 发布检查清单

> 状态：Active
> 更新日期：2026-08-27
> 适用范围：Agent Platform v2

## 1. 发布级别

| 级别 | 允许范围 | 最低要求 |
|---|---|---|
| 本地开发 | 单机开发和自动化测试 | SQLite/local provider 可作为明确标识的测试替身 |
| 内部 Shadow | 受控账号验证 Agent 行为 | 认证、功能开关、资源归属、脱敏、幂等和回滚开关 |
| 生产发布 | 真实用户主链路 | PostgreSQL、真实 Provider、HTTPS、正式域名、备份恢复和全部 Release Gate |

生产环境必须：

```env
APP_ENV=production
ENFORCE_RELEASE_CHECKS=true
DEBUG=false
ENABLE_DOCS=false
AUTO_CREATE_DB=false
AGENT_SHADOW_API_ENABLED=false
AGENT_RUN_STORE_BACKEND=postgresql
DATABASE_URL=postgresql+asyncpg://...
```

## 2. 必填配置

| 类别 | 要求 |
|---|---|
| 数据库 | `DATABASE_URL=postgresql+asyncpg://...`，迁移到唯一 Alembic head |
| 认证 | `SECRET_KEY` 至少 32 位随机字符串 |
| 模型 | 显式配置核心功能 Provider、Model 和 Prompt Version |
| 域名 | `PUBLIC_BASE_URL`、`CORS_ALLOW_ORIGINS`、`TRUSTED_HOSTS` 使用正式 HTTPS 域名 |
| 队列 | `TASK_QUEUE_BACKEND=redis_rq` 且禁止 local fallback |
| 向量 | 真实 Qdrant/Embedding；生产禁止 hash embedding |
| 运维 | metrics、alert、backup、retention 和恢复责任人 |
| Agent | `AGENT_SHADOW_API_ENABLED=false`、`AGENT_RUN_STORE_BACKEND=postgresql`；生产 Agent 路径仍须通过真实 PostgreSQL、多实例、恢复和 durable worker 晋级门 |

## 3. 质量门

从仓库根目录执行：

```powershell
backend\.venv-codex\Scripts\python.exe scripts\run_quality_gate.py --profile backend --mode release --report artifacts\quality-gate\backend-release.json
backend\.venv-codex\Scripts\python.exe scripts\run_quality_gate.py --profile contracts --mode release --report artifacts\quality-gate\contracts-release.json
backend\.venv-codex\Scripts\python.exe scripts\run_quality_gate.py --profile frontend --mode release --report artifacts\quality-gate\frontend-release.json
```

E2E：

```powershell
$env:E2E_PYTHON='F:\mianshi agent\backend\.venv-codex\Scripts\python.exe'
cd frontend
npm.cmd run e2e
```

规则：

- CI 覆盖率 ratchet 保持 64%；
- Release 覆盖率保持 85%；
- 不得降低阈值、排除核心代码、删除测试或用 Mock 伪造生产证据；
- 依赖审计、Secret Scan、OpenAPI Contract、Agent/Skill/MCP Registry 任一阻断失败都不得发布；
- 质量报告必须绑定当前 worktree/commit，不能复用旧报告冒充本次结果。

## 4. 安全与授权检查

1. 生产不公开 `/docs`、`/redoc`、`/openapi.json`。
2. 简历列表不返回正文，所有用户资源按当前用户过滤。
3. Agent Tool 同时校验 Run user、audience、Agent allowlist 和数据库 owner。
4. 跨用户与不存在的 Shadow 资源返回相同公共失败形态。
5. Trace 不包含简历正文、JD、回答、联系方式、Token、内部 state 或完整 Tool Result。
6. 高风险和写 Tool 默认需要审批；当前 Shadow Registry 只允许两个只读 Tool。
7. 日志和 Artifact 不包含数据库凭证、原始支付历史载荷或用户正文。

## 5. 主链路冒烟

1. 注册、登录和会话刷新。
2. 上传文本/PDF/DOCX 简历。
3. 模板优化和 JD 适配。
4. 创建面试、生成问题、提交回答和完成报告。
5. Markdown/DOCX/PDF 导出。
6. 账号导出和删除。
7. 越权访问返回 404/401。
8. 超长或非法输入被拒绝。
9. 系统状态与 release checks 无 production critical。
10. 退役支付、组织、公司画像 CRUD、运营后台和质量反馈入口不存在。

## 6. Agent Shadow 验收

仅内部环境：

1. 默认关闭时返回 404，且不进入 OpenAPI。
2. 创建 Run 必须提供 `Idempotency-Key`。
3. 同请求同 Key 返回同一 Run；不同请求同 Key 返回 409。
4. 当前用户 Resume rewrite 和 Interview coach 可通过真实只读 adapter 完成。
5. 跨用户 Resume/Interview 读取失败且无存在性泄露。
6. GET/cancel/retry 只能操作自己的 Run。
7. 响应不含内部 state、完整 Tool Result、指纹和内部异常类。
8. 生产启用该开关时 release check 为 critical。

## 7. 数据迁移与恢复

- 真实 PostgreSQL 上执行 Phase 1B 只读审计；
- 记录迁移前后 row count、owner 映射、孤儿记录和稳定列 checksum；
- 执行 upgrade、rollback、backup/restore；
- 历史组织、支付、质量和公司画像数据必须有 retain/export/anonymize/legal-hold/delete 决策；
- 没有真实 PostgreSQL 证据时不得宣称 Phase 1B 完成。

## 8. 回滚

1. 保留上一版前后端制品和数据库备份。
2. Agent 异常时首先关闭 Agent/Shadow 功能开关，不破坏稳定主链路。
3. 数据变更使用 expand/migrate/contract，contract 前必须验证旧版本兼容。
4. 高错误率、事实安全回归或跨用户风险出现时立即停止灰度。
5. 回滚后重新执行相关质量门并保存机器可读证据。

## 9. 当前生产阻断

截至 2026-08-27，以下证据尚未具备，因此不能把整体生产就绪度宣称为 90+：

- 真实 PostgreSQL Phase 1B 演练；
- PostgreSQL Agent Run Store 的真实多实例并发、租约接管、取消竞争和恢复演练；
- Redis/RQ Agent durable worker 的 kill/restart、重复投递和取消恢复；
- 网络 MCP Server；
- Agent SLO 与真实 Provider 成本证据；
- 至少 120 条分层简历样本和人工双盲效果评测。
