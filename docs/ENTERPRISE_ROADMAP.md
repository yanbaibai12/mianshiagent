# 企业化架构路线

## 目标架构

当前 MVP 是单体 FastAPI + React。企业化后仍可先保持单体，但边界要清晰：

- Identity：账号、认证、权限、租户。
- Resume：上传、解析、版本、模板优化、JD 适配。
- Interview：题库生成、作答、评分、报告。
- Billing：套餐、订单、权益、用量。
- Ops：审计、日志、模型成本、内容风控。

## 后端模块

### 1. 租户与权限

- tenants
- tenant_members
- roles
- permissions
- API 权限中间件

### 2. 计费与权益

- plans
- subscriptions
- orders
- usage_records
- quota_balances
- 每次 LLM 调用写 usage，按用户和租户聚合。

### 3. 审计与合规

- audit_logs
- data_export_jobs
- data_deletion_jobs
- admin_access_logs

### 4. LLM 编排

- 模型供应商配置表。
- Prompt 版本管理。
- 调用成本统计。
- JSON 输出 schema 校验。
- 自动降级：主模型失败切备用模型或 local fallback。

### 5. 异步任务

- 简历解析、优化、报告生成可进入任务队列。
- 返回 job_id，前端轮询或 SSE。
- 生产优先 Redis Queue / Celery / Dramatiq。

## 前端模块

### 1. 工作台

- 简历数量、面试次数、待完成事项。
- 系统状态与套餐权益。
- 最近报告和薄弱点趋势。

### 2. 简历版本

- 原始版、模板优化版、JD 定向版。
- 修改 diff。
- 一键复制和导出。

### 3. 面试训练

- 按项目/要点分组。
- 题目进度。
- 弱项复练。
- 报告复盘。

### 4. 机构后台

- 学员列表。
- 班级/岗位方向。
- 使用数据。
- 批量导入导出。

## 数据库从 MVP 到生产

### MVP

- SQLite
- 本地文件
- local LLM fallback

### 可收费版本

- PostgreSQL
- 对象存储
- Redis
- 真实 LLM
- 支付回调

### 企业版

- PostgreSQL 高可用
- Redis 集群
- 对象存储加密
- 审计日志不可变存储
- 私有化部署脚本

## 质量保障

1. API 冒烟脚本：注册、上传、优化、出题、评分、报告。
2. Prompt 回归集：固定简历样本检查输出结构和质量。
3. 安全回归：未登录、越权访问、超长输入、限流、导出权限。
4. 前端构建：`npm run build`。
5. 后端导入与健康检查：`import app.main`、`/health`、`/api/system/status`。
