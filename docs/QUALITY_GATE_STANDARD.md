# 企业级质量门与发布准入标准

> 文档版本：1.4.0
> 状态：工程 Release Gate 已通过；生产准入仍受数据与效果证据阻断
> 生效条件：上位开发规范经项目维护者批准
> 编制日期：2026-08-27
> 适用范围：后端、前端、Agent Harness、MCP、Skills、Prompt、模型配置、数据库迁移和部署配置
> 上位文档：[`AGENT_PLATFORM_DEVELOPMENT_SPEC.md`](./AGENT_PLATFORM_DEVELOPMENT_SPEC.md)

---

## 1. 目标

质量门的目标不是让 CI 显示绿色，而是阻止以下风险进入生产：

- 错误或无法回滚的代码；
- 无测试的业务变更；
- 虚构简历内容；
- Agent 工具越权；
- Prompt/Skill/模型质量退化；
- 高危依赖漏洞和密钥泄露；
- 不可恢复的任务和数据库迁移；
- 没有证据、不可追踪或无法复现的 AI 输出；
- 文档声明和实际检查结果不一致。

质量门是 **stop-the-line** 机制。任何阻断项失败时，功能不得合并、发布或对用户开放。

---

## 2. 治理原则

1. **失败默认关闭**：检查无法执行视为失败，不得视为通过。
2. **证据优于声明**：README、MR 或人工口头说明不能代替 CI 报告。
3. **变更必触发评测**：代码、Prompt、Skill、模型、工具、知识库或 Schema 变化都必须触发对应测试。
4. **高风险无豁免**：事实虚构、越权、密钥泄露、不可逆迁移和 Critical 漏洞不得豁免。
5. **结果可复现**：质量报告必须绑定 commit、依赖锁、模型版本、Prompt/Skill 版本和数据集版本。
6. **分层验证**：先运行快速静态和单元检查，再运行集成、E2E、Agent Eval、安全和发布检查。
7. **独立评判**：生成模型不得成为自己输出的唯一评分者。
8. **不以平均值掩盖严重问题**：即使平均分达标，单个虚构事实或跨用户泄露也必须阻断。

---

## 3. 质量门总览

| Gate | 名称 | 触发时机 | 失败后果 |
|---|---|---|---|
| G0 | 需求与设计门 | 开发前 | 不得开始实现 |
| G1 | 本地工程门 | 提交前 | 不得提交 |
| G2 | CI 静态与测试门 | Push/MR | 不得合并 |
| G3 | 数据与契约门 | MR/迁移变更 | 不得合并 |
| G4 | Agent 与 AI Eval 门 | Prompt/Skill/Agent/模型变更 | 不得合并或灰度 |
| G5 | 安全与隐私门 | MR/每日/发布前 | 不得合并或发布 |
| G6 | 性能与韧性门 | 发布候选 | 不得发布 |
| G7 | 发布就绪门 | 部署前 | 不得部署 |
| G8 | 灰度与生产门 | 部署后 | 自动回滚或停止扩量 |

---

## 4. G0：需求与设计门

以下内容必须在编码前完成：

- 明确用户问题、业务目标和非目标；
- 可测试的验收标准；
- 数据分类和隐私影响；
- 失败、取消、重试和回滚行为；
- API/事件/Schema 契约；
- Agent 与普通代码的边界；
- MCP Tool 权限和风险等级；
- Prompt Injection 和越权威胁模型；
- 评测集和成功阈值；
- 数据库迁移和回滚策略；
- 监控指标、告警和 owner。

满足以下任一条件必须写 ADR：

- 新增 Agent；
- 新增或扩大 MCP Tool 权限；
- 更换模型供应商或模型主版本；
- 改变 Agent 编排和 handoff；
- 改变敏感数据持久化；
- 引入新数据库、中间件或外部服务；
- 下调任何质量阈值。

---

## 5. G1：本地工程门

开发者提交前必须执行与变更相关的检查，并在 MR 中记录真实结果。

### 5.1 统一执行入口

Phase 0 已建立统一质量门，Phase 1A 继续使用同一阻断入口。开发者应从仓库根目录执行：

```powershell
# 使用已安装 backend/requirements-dev.txt 的 Python
python scripts/run_quality_gate.py --profile backend --mode ci
python scripts/run_quality_gate.py --profile frontend --mode ci
python scripts/run_quality_gate.py --profile contracts --mode ci

# 完整 CI 门
python scripts/run_quality_gate.py --profile all --mode ci

# 发布候选门；当前覆盖率不足 85% 时必须真实失败
python scripts/run_quality_gate.py --profile backend --mode release

# Git 工作区审查
git diff --check
git status --short
```

可通过 `--report artifacts/quality-gate/<name>.json` 指定机器可读报告路径。脚本运行全部检查后汇总失败，不以 fail-fast 隐藏其他缺陷；报告包含 Git SHA、命令、工作目录、退出码、耗时、输出尾部和证据 SHA-256。

### 5.2 当前渐进纳管边界

- 后端 Ruff lint 已覆盖 `app`、`tests`、`scripts`；
- Ruff format 当前阻断 12 个既有受控内核模块，并额外阻断 Agent Platform 与 Shadow API；存量格式债务不得被描述为已清零；
- mypy 当前阻断 20 个 source files，覆盖 Agent Platform、Shadow API 与既有受控内核；新增 Harness/MCP/Agent/Skill 后端代码必须进入受控范围；
- 全量 mypy 基线为 65 个 source files 中 31 个文件、187 个错误；禁止使用全局 `ignore_errors` 伪造通过；
- 前端 TypeScript strict 和 ESLint 继续阻断；遗留 `any` 与 effect 规则采用 ratchet，新建 `src/agents`、`src/harness`、`src/mcp`、`src/skills` 必须执行严格规则；
- Agent/Skill Registry 当前为 `active` shadow runtime：5 个 Agent、4 个 Skill 均有真实入口与契约校验；这仍不代表已替换生产主链路；
- Agent 激活时必须使用 SemVer、非空 owner/description、正整数预算和 `repository/path.py:symbol` entrypoint；校验器会静态解析文件并确认顶层 symbol 存在，不通过导入执行代码来“验证”；
- Skill 激活时必须使用 SemVer、仓库内真实目录和非空 `SKILL.md`；`inputs`/`outputs` 必须是具名、类型化、带描述的契约字段，输入还必须声明 `required`；
- 注册表、OpenAPI `$ref` 依赖闭包、Secret scan 跳过计数和 Git 工作区证据均有自动化回归测试。

---

## 6. G2：CI 静态与测试门

### 6.1 后端门槛

- Ruff lint：0 error；
- Ruff format：发布目标为全量 0 diff；Phase 0 CI 只对受控模块阻断；
- 类型检查：发布目标为全量 0 error；Phase 0 CI 只对受控模块阻断；
- 单元测试：100% 通过；
- 分支/并发/错误路径测试：100% 通过；
- 总行覆盖率：≥ 85%；
- 新增或修改行覆盖率：≥ 95%；
- Harness、授权与资源隔离、证据验证、幂等和恢复等关键模块覆盖率：≥ 95%；
- Alembic 只能有 1 个 head；
- `git diff --check`：0 error；
- Python 已知依赖漏洞：0；CI 在洁净虚拟环境安装 `requirements-dev.txt` 后，通过 OSV 审计全部已安装生产与开发依赖，依赖收集失败也必须阻断；
- 已知失败、skip 或 xfail 必须有 Issue、owner 和到期日期。

### 6.2 前端门槛

- ESLint：0 error；warning 不得增加；
- TypeScript：0 error；
- 单元/组件测试：100% 通过；
- 生产构建：成功；
- high/critical npm 漏洞：0；
- 核心页面无未处理 Promise rejection；
- 关键交互满足键盘操作和基础无障碍检查；
- 不得把 Token、API Key 或完整敏感数据输出到浏览器日志。

### 6.3 CI Ratchet 与发布门

项目采用双层门槛，防止用存量债务阻塞所有治理工作，也防止把低基线包装成企业发布达标：

| 指标 | CI 模式 | Release 模式 |
|---|---:|---:|
| 后端总行覆盖率 | `>=64%`，只允许提高 | `>=85%` |
| Ruff lint | 全量阻断 | 全量阻断 |
| Ruff format | 12 个既有受控内核模块 + Agent Platform/Shadow API | 发布前应逐步扩展到全量 |
| mypy | 20 个受控 source files | 发布前必须有明确的全量收敛计划和批准基线 |
| Agent/Skill Registry | `active` shadow runtime 必须非空且 entrypoint 可验证 | 生产启用仍需持久化、SLO 与发布审批 |

`64%` 不是企业发布标准。任何报告、README 或简历均不得写成“项目后端覆盖率达到企业级 85%”。当 release 模式因覆盖率失败时，该失败是有效的发布阻断证据，不得下调阈值或修改报告结果。

### 6.4 E2E 门槛

至少覆盖：

1. 注册/登录；
2. 上传文本、PDF 和 DOCX；
3. 简历解析；
4. 基于证据的简历改写；
5. JD 适配；
6. 创建 Agent Run；
7. Agent 进度和 SSE；
8. 动态面试；
9. 回答评分；
10. 报告和简历导出；
11. 取消、超时、重试和恢复；
12. 未登录、越权和跨用户访问；
13. MCP 审批；
14. 移动端核心布局。

E2E 不得依赖开发者机器已有进程；必须自行启动隔离环境和唯一数据库。

---

## 7. G3：数据、迁移与契约门

### 7.1 数据库迁移

每个 Alembic 迁移必须验证：

- 空数据库 `upgrade head`；
- 生产前一版本数据库升级；
- 必要时 `downgrade`；
- 数据保留和转换结果；
- 索引、唯一约束和外键；
- 长事务和锁影响；
- 迁移失败后的恢复；
- PostgreSQL 实测，不以 SQLite 成功代替。

破坏性迁移必须使用 expand/migrate/contract：

1. 先增加兼容结构；
2. 双读/双写或离线迁移；
3. 校验数据；
4. 切换读取；
5. 最后删除旧结构。

禁止在同一发布中直接删除仍被旧代码读取的列或表。

### 7.2 API 契约

- OpenAPI 必须可生成；
- 请求和响应 Schema 必须版本化；
- 删除字段必须经过废弃期；
- 新增必填字段必须提供兼容策略；
- 错误码必须稳定；
- Agent、Tool 和 Skill 输出必须通过 JSON Schema；
- MCP Tool 输入输出合约必须有 contract tests；
- 前端 TypeScript 类型应从合约生成或通过一致性测试。

### 7.3 事件契约

Agent Event 必须至少包含：

```json
{
  "event_id": "uuid",
  "run_id": "uuid",
  "step_id": "uuid",
  "sequence": 1,
  "event_type": "step.started",
  "schema_version": "1.0",
  "occurred_at": "RFC3339",
  "producer": "harness",
  "payload": {}
}
```

事件必须按 `run_id + sequence` 唯一，消费方必须幂等。

---

## 8. G4：Agent 与 AI Eval 门

### 8.1 触发条件

以下任何变化都必须运行关联 eval：

- System Prompt；
- Prompt 模板；
- Skill；
- Agent 指令；
- Agent 划分或 handoff；
- MCP Tool 描述、参数和权限；
- 模型或模型参数；
- RAG chunk、Embedding、Rerank；
- 输出 Schema；
- 评分类目；
- 知识库批量更新。

### 8.2 Agent 基础指标

| 指标 | 阻断阈值 |
|---|---:|
| 输出 Schema 有效率 | ≥ 99.5% |
| 任务成功率 | ≥ 98.0% |
| 正确终止率 | ≥ 98.0% |
| Agent 路由准确率 | ≥ 95.0% |
| Tool 选择准确率 | ≥ 95.0% |
| Tool 参数 Schema 有效率 | 100% |
| Handoff 契约有效率 | 100% |
| 无必要重复工具调用率 | ≤ 2.0% |
| 循环失控 | 0 |
| 未审批 R3/R4 操作 | 0 |
| 跨用户/跨资源越权 | 0 |
| Trace 完整率 | 100% |

### 8.3 面试质量指标

| 指标 | 阻断阈值 |
|---|---:|
| 问题具有证据或明确知识来源 | ≥ 95% |
| 核心能力覆盖率 | ≥ 90% |
| 同义重复问题率 | ≤ 8% |
| 无意义模板问题率 | ≤ 5% |
| 不应出现的内部元问题 | 0 |
| 评分 Schema 有效率 | ≥ 99.5% |
| 与专家评分相关性 | Spearman ≥ 0.70 |
| 严重评分反转 | 0 |
| 相同答案重复评分标准差 | ≤ 0.35/10 |

### 8.4 评测方法

评测必须包含：

- 确定性规则检查；
- 人工金标准；
- 盲评 pairwise comparison；
- 独立 judge 模型作为辅助，不作为唯一依据；
- 不同岗位、年限、简历质量和输入长度分层；
- Prompt Injection、异常 JSON、工具错误和超时；
- 多次重复运行评估稳定性；
- 基线模型/流程对照。

### 8.5 回归判断

新版本必须同时满足：

- 所有绝对阻断阈值；
- 核心总分不低于当前生产基线；
- 目标改进指标有统计意义提升；
- 任一关键用户分层不得出现显著退化；
- 成本或延迟明显增加时，必须证明质量收益值得。

不得只报告“平均分提高”，必须提供分层结果、失败样本和置信区间。

---

## 9. G5：安全与隐私门

### 9.1 阻断条件

以下任一项存在时不得合并或发布：

- Critical/High SAST 漏洞；
- Critical/High 可利用依赖漏洞；
- Secret、Token、私钥或真实 `.env` 进入 Git；
- SQL 注入、命令注入、路径穿越、SSRF；
- 跨用户读取或写入；
- Prompt Injection 能改变系统策略或扩大 Tool 权限；
- 敏感信息写入普通日志或 Trace；
- 未经审批执行 R3/R4 Tool；
- Token audience 不验证或 token passthrough；
- Agent 能执行任意 SQL、Shell 或代码；
- 删除、覆盖或批量导出缺少二次确认和审计；
- 用户删除后高敏数据仍无合法理由长期保留。

### 9.2 必测攻击面

- Web/API：认证、授权、CSRF、XSS、CORS、Host、上传、反序列化；
- Agent：Prompt Injection、工具描述注入、间接注入、越权委派；
- MCP：伪造 Server、恶意 Tool 输出、SSRF、token redirect、scope 扩大；
- RAG：恶意文档、数据投毒、跨用户向量召回；
- 导出：Markdown/HTML/DOCX 公式或链接注入；
- 供应链：恶意 Skill、Prompt、MCP 包和依赖；
- 日志：PII、密钥、完整回答和模型错误泄露。

### 9.3 隐私

- 高敏原文默认不进入第三方 eval；
- Eval 数据必须脱敏并有来源授权；
- 生产 Trace 默认保存摘要和哈希，不保存完整思维过程；
- 数据保留期限必须配置并可执行删除；
- 用户导出和删除必须有端到端测试；
- 外部模型供应商的数据使用、保留和训练策略必须记录。

---

## 10. G6：性能与韧性门

发布候选必须通过：

- 正常负载；
- 峰值负载；
- 长上下文；
- 大文件上传；
- Redis 不可用；
- Qdrant 不可用；
- 模型超时和限流；
- worker 中途退出；
- 重复消息和重复回调；
- 数据库连接耗尽；
- SSE 断线重连；
- 用户取消；
- 恢复和回放。

### 10.1 初始门槛

| 指标 | 门槛 |
|---|---:|
| 非模型 API p95 | ≤ 500ms |
| Agent Run 入队 p95 | ≤ 2s |
| 数据库错误率 | < 0.1% |
| Tool 调用系统错误率 | < 1.0% |
| worker 崩溃后恢复成功率 | ≥ 99.5% |
| 重复请求产生重复副作用 | 0 |
| 取消后继续创建新副作用 | 0 |
| 内存持续增长 | 无可复现泄漏 |

模型延迟采用分位数和超时率监控，不用单一平均值。

---

## 11. G7：发布就绪门

发布前必须具备：

- 版本化 release notes；
- 数据库迁移计划和恢复点；
- 配置差异审查；
- 生产密钥和域名验证；
- PostgreSQL、Redis、Qdrant 健康；
- 备份恢复演练记录；
- 全量质量门报告；
- 关键 Dashboard 和告警；
- 灰度计划；
- 自动或人工回滚步骤；
- 值班 owner；
- 已知问题和残余风险；
- 模型、Prompt、Skill、Agent 和 Tool 版本清单。

发布检查不得由请求者本人单独批准。至少需要一名代码评审者和一名质量/发布责任人确认。

---

## 12. G8：灰度与生产门

### 12.1 灰度顺序

```text
内部测试账号
→ 5% 受控用户
→ 20%
→ 50%
→ 100%
```

每阶段至少观察：

- 错误率；
- Run 失败率；
- Tool 调用异常；
- 越权和安全告警；
- 简历回滚率；
- 用户接受率；
- 输出事实风险；
- token 和成本；
- p95/p99 延迟。

### 12.2 自动停止条件

以下任一发生立即停止扩量并评估回滚：

- 发现一例确认的简历虚构事实；
- 发现一例跨用户数据访问；
- 未审批敏感工具调用；
- 关键 Run 失败率超过基线 2 倍；
- 简历回滚率超过基线 1.5 倍；
- Critical 安全告警；
- 数据迁移异常或无法恢复；
- Trace 完整率低于 99%。

---

## 13. 简历改写专用质量门

完整规范见 [`RESUME_REWRITE_EVALUATION.md`](./RESUME_REWRITE_EVALUATION.md)。以下为绝对阻断项：

- 新增无证据公司、职位、项目、技能、职责、数字、奖项或时间：0；
- 身份和时间线破坏：0；
- 删除关键事实但不提示用户：0；
- ATS 结构解析成功率：100%；
- 每条实质改写可追踪到证据：100%；
- 盲评胜率达到规定阈值；
- 任一岗位/年限分层显著退化：不允许；
- PII 错配、串用户或外泄：0。

内部 ATS 分数提高不能单独作为通过依据。

---

## 14. 质量报告格式

每次 CI 和发布候选必须生成不可变报告：

```json
{
  "schema_version": "1.0",
  "commit": "git-sha",
  "created_at": "RFC3339",
  "environment": "ci",
  "code": {
    "unit_tests": "pass",
    "coverage": 0.91,
    "changed_line_coverage": 0.98
  },
  "security": {
    "critical": 0,
    "high": 0,
    "secret_findings": 0
  },
  "agent_eval": {
    "suite_version": "agent-core-1.2.0",
    "pass": true,
    "routing_accuracy": 0.97,
    "tool_accuracy": 0.96
  },
  "resume_eval": {
    "suite_version": "resume-rewrite-1.0.0",
    "pass": true,
    "unsupported_claims": 0,
    "pairwise_win_rate": 0.74
  },
  "approvals": [],
  "result": "pass"
}
```

报告必须作为 CI Artifact 保存，并能通过 commit 或发布版本查询。

---

## 15. 例外与豁免

### 15.1 不可豁免

- 虚构或错配用户事实；
- 跨用户越权；
- Critical/High 可利用安全漏洞；
- 密钥泄露；
- 未审批破坏性工具调用；
- 无回滚路径的破坏性迁移；
- 数据丢失；
- 法律和隐私要求。

### 15.2 可临时豁免

仅低风险非关键指标可以申请临时豁免，且必须包含：

- 具体失败项；
- 用户影响；
- 风险等级；
- 临时缓解；
- owner；
- 修复 Issue；
- 最迟到期时间，不超过 14 天；
- 至少两人批准。

到期未修复时自动阻断下一次发布。

---

## 16. 当前基线审计结果

截至 2026-08-27，当前工作区本地验证结果：

- 后端 Release Gate：116 个 pytest 测试与 19 个 subtests 通过，总行覆盖率 `86.03%`；Ruff、受控 Ruff format、mypy、pip-audit、Alembic heads 全部通过；
- 前端 Release Gate：ESLint、7 个 Vitest 单测及覆盖率、TypeScript、生产 build、npm high audit 全部通过；
- E2E：Chromium 下 3 个核心场景通过；
- 契约与安全 Release Gate：文档治理、部署运行时一致性、生产 Shadow fail-closed、OpenAPI、Agent、MCP、Skills、密钥扫描和 Agent fact-safety eval 全部通过；
- OpenAPI：历史基线 98 个 operation，当前活动 79 个；19 项删除均经 ADR-0002 精确批准，未批准 breaking change 为 0；
- Agent shadow runtime：5 个 Agent、4 个 Skill、2 个只读 MCP-compatible Tool；具备预算、超时、取消、失败重试、幂等、Checkpoint、Trace、handoff、工具 allowlist、审批和同一 Run 并发串行化；
- 自动事实安全评测：8/8 通过，覆盖 PII 排除、Evidence Hash、防篡改、空证据不生成、来源精确和输出上限；
- 统一证据报告：`artifacts/quality-gate/2026-08-27-all-release-final-v2.json`；报告覆盖 21 项阻断检查，并记录 Git SHA、工作区指纹和证据哈希。

工程质量门达到本阶段 Release 标准后，仍不得宣称生产平台完成：PostgreSQL Run Store、事务幂等、执行租约和取消竞争已完成代码与 SQLite 合同测试，但 Phase 1B/0018 尚无真实 PostgreSQL 升降级、并发、多实例和恢复演练；durable worker 与 kill/restart/重复投递恢复未完成；MCP Gateway 不是网络 MCP Server；真实只读领域适配器仍未晋级为生产 Tool 服务；简历改写尚缺至少 120 条分层样本、独立人工盲评、置信区间和群体退化检查。上述项目属于生产准入和效果证明阻断项，不得用 SQLite、SQL 编译、Mock、自动测试或模型自评分替代。
