# 发布检查清单

## 发布模式

| 模式 | 目标 | 允许配置 |
|---|---|---|
| MVP 演示 | 本机或内测演示 | SQLite、local LLM fallback、本地前端 |
| 公测发布 | 小流量真实用户 | PostgreSQL、真实 LLM、HTTPS、正式域名 |
| 商业发布 | 可收费交付 | 公测配置 + 计费/权益开关 + 成本监控 |

生产环境建议保持：

```env
APP_ENV=production
ENFORCE_RELEASE_CHECKS=true
DEBUG=false
ENABLE_DOCS=false
```

后端启动时会执行 `assert_release_ready(settings)`。只要生产环境存在 critical 项，服务会拒绝启动。

## 必填环境变量

| 类别 | 变量 |
|---|---|
| 数据库 | `DATABASE_URL=postgresql+asyncpg://...` |
| 认证 | `SECRET_KEY` 至少 32 位随机字符串 |
| 模型 | `LLM_PROVIDER`、`LLM_MODEL`、`LLM_API_KEY` |
| 域名 | `PUBLIC_BASE_URL`、`CORS_ALLOW_ORIGINS`、`TRUSTED_HOSTS` |
| 安全 | `DEBUG=false`、`ENABLE_DOCS=false`、`ENFORCE_RELEASE_CHECKS=true` |
| 商业化 | `BILLING_ENABLED`、`PAYMENT_PROVIDER`、`BILLING_UPGRADE_CONTACT`、套餐额度和价格 |

参考模板：`backend/.env.production.example`。

## 构建与迁移

后端：

```bash
cd backend
alembic upgrade head
python -c "import app.main; print('backend import ok')"
pip-audit -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

前端：

```bash
cd frontend
npm ci
npm run build
npm audit --json
```

## 安全检查

上线前必须确认：

1. `/health` 可以公开访问，但不返回敏感信息。
2. `/api/system/status` 和 `/api/system/release-checks` 需要登录。
3. `SECRET_KEY`、LLM Key、数据库密码不提交到仓库。
4. CORS 只允许正式前端域名。
5. Trusted Host 只允许正式 API 域名。
6. 生产不公开 `/docs`、`/redoc`、`/openapi.json`。
7. 简历列表接口不返回简历原文。
8. 用户只能访问自己的简历、面试、报告。
9. 上传文件大小和文本长度限制生效。
10. 日志不记录完整简历、JD、回答、Token、API Key。

## 商业化检查

1. 免费版必须允许用户完成一次完整体验。
2. 完整报告、导出、多 JD 适配、多简历版本需要明确付费墙。
3. `PRO_MONTHLY_PRICE_CNY` 和 `SPRINT_PACKAGE_PRICE_CNY` 必须大于 0。
4. Pro 权益额度不能低于免费版。
5. `PAYMENT_PROVIDER=manual` 时必须配置 `BILLING_UPGRADE_CONTACT`。
6. 接第三方支付前必须完成订单回调验签、幂等处理和对账流程。
7. 每次 LLM 调用必须能估算成本，避免免费额度被刷穿。

## 冒烟测试

使用测试账号完成：

1. 注册、登录、刷新后仍保持会话。
2. 粘贴文本简历上传成功。
3. 模板优化返回结构化结果。
4. JD 适配返回匹配分和弱项。
5. 创建面试并生成问题。
6. 提交至少 3 个回答并生成报告。
7. 报告导出返回 Markdown 内容。
8. 越权访问其他用户资源返回 404/401。
9. 超长输入返回 400。
10. 登录后查看系统状态，发布检查无 critical。

## 回滚

1. 前端保留上一版 `dist` 静态产物。
2. 后端镜像或部署包按版本号保留。
3. 数据库迁移前先备份。
4. 发布后出现高错误率，先回滚后端，再回滚前端。
5. 涉及数据结构变化时，必须准备 Alembic downgrade 或只做向前兼容迁移。

## 当前不能直接商业发布的情况

任一条件满足都应先整改：

1. 仍使用 SQLite。
2. 仍使用 `LLM_PROVIDER=local`。
3. 没有 HTTPS。
4. 发布检查存在 critical。
5. 前端构建失败或依赖审计存在 high/critical。
6. 后端 `pip-audit` 尚未执行或存在 high/critical。
7. 未完成隐私声明、用户删除和数据导出策略。
8. 未建立 LLM 成本估算和免费额度风控。
