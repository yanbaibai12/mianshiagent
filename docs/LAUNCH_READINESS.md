# 发布就绪清单

## 发布原则

本项目可以按两种模式发布：

1. 演示发布：`APP_ENV=local`，SQLite + local RAG + local LLM fallback，用于内部演示。
2. 商业发布：`APP_ENV=production`，PostgreSQL + 真实 LLM + HTTPS + 正式域名 + 发布检查通过。

生产环境如果 `ENFORCE_RELEASE_CHECKS=true`，后端会在启动时执行发布检查。存在 critical 项时会拒绝启动。

详细执行清单见：`docs/RELEASE_CHECKLIST.md`。

## 必须通过的检查

### 后端

- `APP_ENV=production`
- `DEBUG=false`
- `AUTO_CREATE_DB=false`，数据库结构只通过 Alembic 迁移创建。
- `SECRET_KEY` 不是默认值，且至少 32 位随机字符。
- `DATABASE_URL` 使用 PostgreSQL，不使用 SQLite。
- `LLM_PROVIDER` 使用真实模型供应商，不使用 `local`。
- `LLM_API_KEY` 已配置。
- `LLM_ALLOW_FALLBACK=false`，模型失败时明确提示，不静默降级为本地规则结果。
- `PUBLIC_BASE_URL` 使用 HTTPS。
- `CORS_ALLOW_ORIGINS` 只包含正式前端域名。
- `TRUSTED_HOSTS` 只包含正式 API 域名。
- `ADMIN_EMAILS` 已配置，尤其是 `PAYMENT_PROVIDER=manual` 时必须有管理员账号处理人工开通。
- `TASK_QUEUE_BACKEND=redis_rq`，`TASK_ALLOW_LOCAL_FALLBACK=false`，API 和 worker 使用同一个 Redis 队列。
- `VECTOR_STORE_BACKEND=qdrant`，`QDRANT_URL` 指向外部 Qdrant，BGE-M3 相关索引维度为 1024。
- `ALERT_NOTIFY_ENABLED=true`，`ALERT_WEBHOOK_URL` 已配置，系统告警能推送到外部渠道。
- `/health` 返回正常。
- 登录后访问 `/api/system/release-checks`，`publishable=true`。
- 登录后访问 `/api/business/entitlements`，确认套餐、用量和剩余额度返回正常。
- 管理员登录后访问 `/admin/system`，确认运营摘要、升级意向和人工开通接口可用。
- 管理员在 `/admin/system` 查看运行告警、队列/Qdrant 状态、告警发送记录和质量评测候选。
- `alembic upgrade head` 可在新数据库上完成初始建表。
- 收费发布时 `BILLING_ENABLED`、`PAYMENT_PROVIDER`、套餐价格和额度配置合理。

### 前端

- `VITE_API_BASE_URL` 指向正式 API 域名。
- `npm run typecheck` 通过。
- `npm run build` 通过。
- `npm audit --json` 无 moderate/high/critical 漏洞。
- 登录、上传文本简历、优化、JD 适配、创建面试、评分、报告导出主链路可用。
- 岗位工作台完整跑通：创建岗位、绑定简历、JD 优化、前后对比、面试训练、报告导出、质量反馈。
- 工作台展示商业化闭环，`POST /api/business/upgrade-request` 能记录升级意向。

### 数据库

- 生产使用 PostgreSQL。
- 初始化表结构完成。
- 开启每日备份。
- 备份恢复流程至少演练一次。
- 敏感数据访问有审计计划。

### 安全

- 全站 HTTPS。
- API Key 不返回前端。
- 简历列表不返回原文。
- 用户只能访问自己的简历、面试、报告。
- 限流开启。
- 上传大小限制开启。
- 日志不得记录完整简历、JD、回答、LLM Key。

## 发布流程

1. 准备 `.env.production`，不要提交真实密钥。
2. 后端执行数据库迁移：

```bash
cd backend
alembic upgrade head
```

3. 后端运行：

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

4. 前端构建：

```bash
cd frontend
npm ci
npm run build
```

5. Nginx/CDN 指向前端 `dist`，API 代理到后端。
6. 登录后检查 `/api/system/release-checks`。
7. 用测试账号完成完整链路。
8. 再开放真实用户注册。

## 上线后监控

必须监控：

- API 错误率。
- LLM 调用失败率。
- 每条完整链路平均成本。
- 注册到上传转化率。
- 上传到报告生成转化率。
- 低分质量反馈数量、开放评测候选数量、已加入回归评测数量。
- 付费转化率。
- 单用户用量异常。

## 暂不建议商业发布的情况

任一条件满足都不建议正式收费：

- 只能使用 local LLM fallback。
- 仍使用 SQLite。
- 没有 HTTPS。
- 发布检查存在 critical。
- `npm audit` 有 high/critical。
- 没有数据删除和用户隐私声明。
- 未估算单次完整链路模型成本。
- 没有 Redis/RQ worker 或外部 Qdrant，只能依赖本地 fallback。
- 低分反馈不能进入人工评测闭环。
