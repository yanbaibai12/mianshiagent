# Docker 部署指南

这套部署配置面向单机或小规模部署候选环境；它提供可复现拓扑，但不等于已经获得生产发布批准。配置包含：

- PostgreSQL
- Redis/RQ worker
- Qdrant
- FastAPI 后端
- React/Vite 前端静态服务
- 前端 Nginx 对 `/api` 的同域反向代理

生产流量仍建议放在云厂商负载均衡、CDN 或宿主机 Nginx 后面，由外层网关负责 HTTPS 证书。

## 1. 准备环境变量

复制 Compose 变量模板：

```bash
cp deploy/compose.env.example deploy/compose.env
```

复制后端生产环境模板：

```bash
cp backend/.env.production.example backend/.env.production
```

编辑 `deploy/compose.env`：

- `POSTGRES_PASSWORD`：使用长随机值，且保持 URL-safe。
- `PUBLIC_BASE_URL`：用户访问的正式前端地址，例如 `https://app.example.com`。
- `CORS_ALLOW_ORIGINS`：正式前端域名。
- `TRUSTED_HOSTS`：同域部署时填前端域名，例如 `app.example.com`。
- `VITE_API_BASE_URL`：同域部署保持 `/api`；独立 API 域名时改为 `https://api.example.com`。

编辑 `backend/.env.production`，至少替换：

- `SECRET_KEY`
- `LLM_PROVIDER`
- `LLM_MODEL`
- `LLM_API_KEY`
- `ADMIN_EMAILS`
- `AGENT_SHADOW_API_ENABLED=false`（生产环境必须保持关闭；启用会触发 critical Release Check 并阻止启动）
- `AGENT_RUN_STORE_BACKEND=postgresql`（生产候选必须使用持久化 Store；memory 仅允许本地开发/测试）
- `ALERT_WEBHOOK_URL` 或先设置 `ALERT_NOTIFY_ENABLED=false`
- 所有 `REPLACE_*` 占位值

Compose 会强制覆盖 Agent/数据库 fail-closed 配置和后端连接变量，确保容器内服务互通：

- `AGENT_SHADOW_API_ENABLED=false`
- `AGENT_RUN_STORE_BACKEND=postgresql`
- `DATABASE_URL=postgresql+asyncpg://...`
- `TASK_REDIS_URL`
- `QDRANT_URL`
- `UPLOAD_DIR`
- `BACKUP_DIR`
- `EMBEDDING_CACHE_DIR`

## 2. 构建并启动

```bash
docker compose --env-file deploy/compose.env build
docker compose --env-file deploy/compose.env up -d
```

`migrate` 服务会在后端启动前执行：

```bash
python -m alembic upgrade head
```

查看服务状态：

```bash
docker compose --env-file deploy/compose.env ps
```

查看后端日志：

```bash
docker compose --env-file deploy/compose.env logs -f backend
```

查看 worker 日志：

```bash
docker compose --env-file deploy/compose.env logs -f worker
```

## 3. 访问与反代

默认前端容器监听宿主机 `8080`：

```text
http://服务器IP:8080
```

正式发布时，把 HTTPS 网关反代到宿主机 `8080`。同域部署下，浏览器请求流程是：

```text
https://app.example.com/api/* -> frontend nginx -> backend:8000/api/*
```

外层 Nginx 示例：

```nginx
server {
    listen 443 ssl http2;
    server_name app.example.com;

    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    client_max_body_size 10m;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

## 4. 发布检查

启动后先检查健康状态：

```bash
curl https://app.example.com/health
```

再登录系统，访问：

```text
/api/system/release-checks
```

只有 `publishable=true` 且 `critical_count=0` 时，才建议开放真实用户。生产环境还必须确认 `AGENT_SHADOW_API_ENABLED=false`、`AGENT_RUN_STORE_BACKEND=postgresql` 且 `DATABASE_URL` 为 `postgresql+asyncpg://...`。Compose 契约只证明配置被强制，不代表当前机器已完成镜像、Compose、迁移或真实 PostgreSQL 演练；Shadow Runtime 晋级前不得通过修改检查逻辑绕过阻断。

## 5. 常用运维命令

重启后端：

```bash
docker compose --env-file deploy/compose.env restart backend worker
```

手动执行迁移：

```bash
docker compose --env-file deploy/compose.env run --rm migrate
```

备份 PostgreSQL：

```bash
docker compose --env-file deploy/compose.env exec -T postgres pg_dump -U interview_agent interview_agent > backup.sql
```

停止服务：

```bash
docker compose --env-file deploy/compose.env down
```

停止并删除数据卷：

```bash
docker compose --env-file deploy/compose.env down -v
```

只在确认不需要保留数据库、上传文件、Qdrant 索引和 Redis 数据时执行 `down -v`。
