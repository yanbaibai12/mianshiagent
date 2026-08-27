# 已知问题与风险登记

> 文档版本：1.3.0
> 状态：Active
> 更新日期：2026-08-27
> Owner：项目维护者、Agent Platform Team、安全负责人
> 原则：只记录仍然真实存在的问题；已解决事项保留证据，不继续作为当前能力声明。

## P0：生产阻断

1. **缺少真实 PostgreSQL 演练**
   当前环境没有可用的 PostgreSQL 审计目标，Phase 1B 只能完成只读审计代码和 SQLite/SQL 编译测试，不能冒充 PostgreSQL upgrade/rollback/restore 演练。环境探测证据见 `artifacts/data-contract/postgresql-environment-probe.json`。

2. **Agent Run Store 尚缺真实 PostgreSQL 与 worker 恢复证据**
   Alembic `0018`、PostgreSQL Run/Step/Trace/Checkpoint Store、事务幂等唯一约束、执行租约和取消保留已实现；但当前机器没有真实 PostgreSQL 演练目标，也尚未接入 Agent durable worker。SQLite 合同测试和 PostgreSQL SQL 编译不能冒充多实例、kill/restart、升级、降级或恢复证据。

3. **简历改写效果未被独立证明**
   当前 Evidence Hash 和 source-exact 重排可以阻止部分虚构，但自动事实安全评测不等于真实效果。仍缺至少 120 条分层样本、人工双盲评测、95% 置信区间和群体退化检查。

4. **MCP 仍是进程内兼容网关**
   已有 Tool Registry、audience、双向 allowlist、approval、timeout、契约校验，以及真实只读 Resume/Interview 数据库适配器和 owner 校验；但它不是网络 MCP Server，尚无跨进程传输、独立身份、网络级取消和服务级 SLO。

## P1：上线前高优先级

1. 认证仍为 MVP 级 HMAC/PBKDF2 方案；生产建议迁移到成熟 session/JWT 方案和 Argon2id，并完成 token rotation/revocation。
2. 限流为单进程内存级；多实例生产必须使用 Redis 或 API Gateway。
3. local LLM 仅用于可重复测试，不代表模型质量；真实 Provider 需要版本冻结、成本门和回归评测。
4. 已有认证、功能开关保护和用户隔离的 Shadow API，并提供按状态/Agent 筛选的游标分页 Run Inspector API；但仍缺 Inspector UI、durable worker 和面向最终用户的生产 Agent API/UI。
5. 同步 MCP handler 超时后底层线程不能被 Python 强制终止；生产 adapter 必须使用可取消 I/O 或进程隔离，并设置下游超时。
6. 全量后端仍有存量格式和类型债务；当前 mypy/format 是受控范围通过，不得表述为全仓严格模式完成。
7. Shadow API 在生产环境被 Release Check 和启动检查强制阻断；在完成 ADR-0004 的晋级门前不得绕过该保护。

## P2：持续改进

1. 前端单测和 Chromium E2E 仍偏少；需增加异常、取消、重试、授权、跨浏览器和生产拓扑场景。
2. `resumes.py`、`jobs.py`、`vector_store.py` 等存量模块覆盖率低于项目平均值，后续按风险继续提升。
3. 已通过 GitHub Actions 将 Phase 0 质量证据绑定合并提交；后续每个发布候选仍必须保持 commit 级证据绑定。
4. 需要定义 Agent SLO：成功率、P95 时延、平均步骤、工具失败率、取消延迟、恢复成功率和单 Run 成本。

## 已解决并有证据

- 支付、公司/组织管理、运营后台和在线质量反馈产品表面已退役；
- OpenAPI 的退役删除均由 ADR-0002 精确批准，未批准 breaking change 必须保持为 0；
- 5 Agents、4 Skills、2 个只读 MCP-compatible Tools 的隔离 shadow runtime 已实现并测试；
- Shadow API 已实现认证、同用户 Run 隔离、幂等、取消、有限重试、错误脱敏、默认关闭和生产阻断；
- Alembic `0018` 和 PostgreSQL Agent Run Store 已实现事务幂等、持久化 Step/Trace/Checkpoint、执行租约、取消保留与错误后重试；
- Resume/Interview Tool 已接入真实数据库只读查询，并对缺失与跨用户资源返回一致的公共失败形态。

> 后端、前端、契约、安全、覆盖率和 E2E 的最终通过数值，以本次工作完成后新生成的机器可读质量门 Artifact 为准；历史报告不得替代当前 worktree 验证。
