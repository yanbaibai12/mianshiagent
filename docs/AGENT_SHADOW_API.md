# Agent Shadow API 操作与安全契约

> 文档版本：1.2.0
> 状态：Accepted for authenticated shadow evaluation
> 日期：2026-08-27
> Owner：Agent Platform Team / Security Owner
> 生产边界：禁止作为生产 Agent API

## 1. 目的

本接口把受控 Harness 接到真实 Resume/Interview 只读领域适配器，用于内部验证：

- Run 生命周期和幂等；
- Supervisor → Specialist handoff；
- Tool allowlist 与 audience；
- 数据库资源归属；
- 事实安全 Skill；
- 取消、失败重试和脱敏后的 Run inspection。

它不替换现有简历、岗位、面试或报告主链路。

## 2. 启用条件

默认配置：

```env
AGENT_SHADOW_API_ENABLED=false
AGENT_RUN_STORE_BACKEND=memory
```

仅本地或受控测试环境可临时设为 `true`。本地默认使用 `memory`；受控 PostgreSQL 环境可设置 `AGENT_RUN_STORE_BACKEND=postgresql`，数据库必须已迁移到 Alembic `0018`。生产环境启用时，`agent_shadow_runtime` Release Check 必须返回 `critical` 并阻止启动。

接口不进入 OpenAPI，且全部要求登录。功能关闭时统一返回 404。

## 3. API

### 创建并执行 Run

```http
POST /api/agent-shadow/runs
Authorization: Bearer <token>
Idempotency-Key: <8-128 characters>
Content-Type: application/json
```

请求示例：

```json
{
  "objective": "生成有证据约束的岗位定向改写建议",
  "input": {
    "mode": "resume-rewrite",
    "resume_id": "00000000-0000-0000-0000-000000000000",
    "jd_text": "Python FastAPI PostgreSQL"
  },
  "budget": {
    "max_steps": 12,
    "max_tokens": 12000,
    "max_tool_calls": 8,
    "timeout_seconds": 60,
    "step_timeout_seconds": 15
  }
}
```

`mode` 契约：

| mode | 必填输入 | 执行 Agent |
|---|---|---|
| `resume` | `resume_id` | `resume-analyst` |
| `resume-rewrite` | `resume_id`, `jd_text` | `resume-rewriter` |
| `jd` | `jd_text` | `jd-analyst` |
| `interview` | `interview_id`, `answer` | `interview-coach` |

同一用户使用相同 `Idempotency-Key` 且请求指纹相同，返回同一 Run；objective、input、start Agent 或 budget 任一变化都返回 409。

### 分页检索 Run

```http
GET /api/agent-shadow/runs?status=completed&current_agent_id=resume-rewriter&limit=20&cursor=<opaque>
```

- 仅返回当前登录用户的 Run 摘要，数据库查询不加载 Step/Trace 子表，也不读取 output/state/checkpoint 等大字段，避免列表查询放大；
- 使用 `(updated_at, run_id)` 降序游标分页，`limit` 范围为 1–100；
- 可按 `status` 和 `current_agent_id` 检索；
- `next_cursor` 是不透明游标，时间戳统一编码为带时区的 UTC；调用方不得解析或自行构造；
- 非法、超长或无时区时间戳游标返回 422；Store 不可用返回 503。

### 查询、取消和重试

```http
GET  /api/agent-shadow/runs/{run_id}
POST /api/agent-shadow/runs/{run_id}/cancel
POST /api/agent-shadow/runs/{run_id}/retry
```

- 只能查询、取消或重试当前用户自己的 Run；其他用户和不存在的 Run 均返回 404。
- 已终态 Run 的 cancel 为幂等操作。
- 只有 failed Run 可重试，最多 3 次 attempt。
- 当前实现同步等待 Shadow Run 结束；未来 durable worker 不得改变幂等和授权语义。

## 4. 数据与输出边界

Tool handler 使用独立 AsyncSession，并同时校验：

1. Harness Run user；
2. Tool audience；
3. Agent 与 Tool 双向 allowlist；
4. Resume/Interview 数据库 `user_id` 归属。

公开响应允许：

- Run ID、状态、当前 Agent；
- token/tool/step 计数；
- 脱敏 Step；
- 仅含 Agent/Tool 名称和通用错误码的 Trace；
- 完成后的业务输出；
- 不含 state 的 Checkpoint 摘要。

公开响应禁止：

- `request_fingerprint`、`idempotency_key`；
- 原始内部 `state`；
- 完整 `last_tool_result`；
- 内部异常类和数据库错误；
- 跨用户资源存在性；
- Token、数据库 URL、密钥。

## 5. 已知限制

- 本地默认 `InMemoryRunStore`，重启会丢失；
- PostgreSQL Run/Step/Trace/Checkpoint Store、事务幂等唯一约束和跨实例执行租约已实现，但尚未完成真实 PostgreSQL 并发与恢复演练；
- 已有分页/筛选 Run Inspector API，但尚无面向最终用户的 Inspector UI；
- 无 durable worker；
- Gateway 是进程内 MCP-compatible 实现，不是网络 MCP Server；
- 自动事实安全检查不能证明招聘者偏好或真实投递效果。

## 6. 生产晋级门

生产 Agent API 至少需要：

1. PostgreSQL Run/Step/Event/Checkpoint Store 在真实 PostgreSQL 上完成迁移、并发和恢复验收；
2. 事务幂等、执行租约、取消竞争和租约过期接管完成多实例演练；
3. Redis/RQ durable worker 与 kill/restart 恢复演练；
4. 网络 MCP 认证、协议契约和审计；
5. Agent SLO、成本、取消延迟和恢复成功率证据；
6. 简历改写人工双盲、95% CI 和群体退化分析；
7. 灰度开关、回滚和主链路对照评测。
