# 已知问题记录

更新时间：2026-07-24

## 环境问题

1. 当前机器的 `python.exe` 是 Windows Store 占位符，不是可直接运行的 Python 解释器。
2. `uv venv --python 3.11` 下载/创建环境长时间卡住，后续改用本机已缓存的 Python 3.12 创建成功。
3. `uv pip install -r requirements.txt` 以及最小依赖集合安装出现长时间卡住，未能完整建立本项目独立 `.venv`。
4. 为先跑通 MVP，当前服务使用了已有环境 `F:\moldflow_worker_system\.venv\Scripts\python.exe` 启动。
5. PDF/DOCX 解析代码已保留为懒加载，但当前验证路径以粘贴文本简历为主。等依赖安装稳定后再完整验证文件上传。
6. 前端升级 Vite 后，旧 `node_modules/.vite` 缓存目录曾被 Windows 锁占用，删除操作被安全策略拦截。当前已改用 `frontend/.vite-cache` 作为 Vite cacheDir 并加入 `.gitignore`。
7. 本轮验证中，旧的 8000 后端进程无法被工具停止重启；新代码已通过 FastAPI `TestClient` 验证，实际访问 8000 前需要手动重启后端进程。
8. Alembic 初始迁移已通过随机临时 SQLite 文件烟测，并已清理本次测试文件；如历史环境残留 `migration_smoke.db`，它会被 `*.db` 忽略。
9. 当前复用的 Python 环境未安装 `pip-audit`，后端依赖漏洞扫描尚未完成；发布前需要在 CI 或生产构建环境补跑。

## 产品与工程问题

1. 当前 SQLite 适合本地 MVP，不适合多人生产环境。已补 Alembic 初始迁移，生产仍需切 PostgreSQL 并在目标环境验证迁移。
2. 本地 `LLM_PROVIDER=local` 是演示兜底，不代表真实模型质量。商业化版本需要接入真实模型并做 Prompt 质量评测。
3. 认证当前使用标准库 HMAC token 与 PBKDF2 密码哈希，适合 MVP 本地少依赖运行。生产建议切换成熟方案：JWT/opaque session + Argon2/bcrypt + refresh token。
4. 当前限流为进程内存级，单实例有效。生产环境需要 Redis/网关级限流。
5. 当前已补 `billing_accounts` 与 `usage_records` 的 MVP 权益框架，但还没有真实订单、支付回调、发票和退款状态机。
6. 当前没有租户模型。B 端商业化前仍需补 `tenant_id` 隔离、机构账号池和管理员权限。
7. 当前没有后台运营系统。企业化交付至少需要用户管理、用量统计、模型成本监控和内容风控面板。
8. 当前前端已完成工作台式 UI 改造，但还没有自动化浏览器测试。后续建议补 Playwright 主链路测试。

## 后续优先级

1. 修复 Python/uv 依赖环境，建立项目自有 `.venv`。
2. 在真实 PostgreSQL 环境执行 Alembic 迁移、备份和回滚演练。
3. 接真实 LLM，建立 20-50 份简历样本评测集。
4. 增加订单、支付回调、审计日志和后台人工开通入口。
5. 增加租户、数据删除、导出和隐私合规模块。
