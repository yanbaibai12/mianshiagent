# Agent Platform v2 所有权与审批矩阵

> 文档版本：1.0.0
> 状态：Phase 0 治理基线
> 编制日期：2026-08-26
> Owner：项目维护者

## 1. 使用方式

当前仓库没有可验证的企业人员目录，因此本文使用**角色所有权**，不虚构个人姓名。进入团队协作或正式发布前，项目维护者必须把每个角色映射到真实负责人，并在仓库保护规则、值班表和 MR 模板中保持一致。

- **A（Accountable）**：最终负责和批准；每项只能有一个；
- **R（Responsible）**：直接实现/运行；
- **C（Consulted）**：必须参与评审；
- **I（Informed）**：需要知会。

## 2. 角色定义

| 角色 | 职责 |
|---|---|
| Project Maintainer | 路线、范围、风险接受、最终合并和发布授权 |
| Agent Platform Owner | Harness、Agent Registry、handoff、预算、恢复和 Trace |
| Backend Owner | API、领域服务、数据库、任务队列和后端测试 |
| Frontend Owner | Web 交互、可访问性、前端测试和浏览器安全 |
| MCP & Skills Owner | MCP Registry/Gateway、Tool Contract、Skill 生命周期 |
| AI Quality Owner | Agent Eval、简历真实性、盲评、数据集和质量阈值 |
| Security & Privacy Owner | 鉴权、最小权限、密钥、威胁模型、PII 与数据保留 |
| Release Owner | CI/CD、部署、备份恢复、灰度、监控和回滚 |

小团队可以一人承担多个 R 角色，但高风险变更的请求者不得同时成为唯一批准者。

## 3. 目录所有权

| 范围 | A | R | 必须咨询 |
|---|---|---|---|
| `backend/app` | Backend Owner | Backend Owner | Security；涉及 Agent 时咨询 Agent Platform |
| `frontend/src` | Frontend Owner | Frontend Owner | AI Quality；涉及敏感数据时咨询 Security |
| `backend/alembic`、模型 | Backend Owner | Backend Owner | Security、Release |
| `scripts/run_quality_gate.py`、`quality/` | AI Quality Owner | AI Quality Owner | Backend、Frontend、Release |
| `backend/app/agents`、Harness（未来） | Agent Platform Owner | Agent Platform Owner | Backend、AI Quality、Security |
| MCP Gateway/Tool（未来） | MCP & Skills Owner | MCP & Skills Owner | Security、Agent Platform、Backend |
| Skills/Prompt（未来） | MCP & Skills Owner | MCP & Skills Owner | AI Quality、领域 Owner |
| `.github/workflows`、部署 | Release Owner | Release Owner | Backend、Frontend、Security |
| 权威文档与 ADR | Project Maintainer | 对应领域 Owner | 所有受影响 Owner |

## 4. 强制审批

| 变更 | 最低批准要求 |
|---|---|
| 普通代码/文档 | 1 名非作者领域评审者 |
| API 破坏性变更 | Backend Owner + 调用方 Owner |
| 数据库 destructive migration | Backend Owner + Release Owner + 备份恢复证据 |
| 新 Agent 或 handoff | Agent Platform Owner + AI Quality Owner |
| 新 MCP Tool / 扩权 | MCP & Skills Owner + Security Owner |
| R3/R4 工具 | Security Owner + Project Maintainer；默认人工批准 |
| Prompt/Skill/模型发布 | AI Quality Owner + 对应领域 Owner；Eval 必须通过 |
| 简历真实性规则 | AI Quality Owner + Project Maintainer；不可豁免虚构事实 |
| 下调质量阈值 | ADR + Project Maintainer + AI Quality + Security/Release（按影响） |
| 生产发布 | Release Owner + 代码评审者；请求者不得单人批准 |

## 5. 事件 Owner

| 事件 | 主责 | 第一动作 |
|---|---|---|
| 简历虚构或证据错配 | AI Quality Owner | 停止扩量、冻结模型/Skill 版本、保全 Trace |
| 跨用户访问或 PII 泄露 | Security Owner | 立即封禁路径、轮换凭据、启动事件响应 |
| Agent 循环/成本失控 | Agent Platform Owner | 中止 Run、收紧预算、回放 Trace |
| 数据迁移异常 | Release Owner | 停止发布、执行回滚/恢复、核对 row count |
| 质量门基础设施故障 | Release Owner | fail-closed，修复检查，不允许跳过 |
| MCP Tool 越权 | Security Owner | 禁用 Tool、吊销授权、审计受影响 Run |

## 6. 质量门所有权

- 质量门脚本由 AI Quality Owner 维护，CI 执行由 Release Owner 负责；
- 各领域 Owner 对其失败项负责，不能由质量 Owner 代替修复；
- `planned` Agent/Skill 不得由文档 Owner 宣称为 `active`；
- 例外必须含 Issue、owner、到期时间和双人批准；不可豁免项永远不得跳过；
- 合并前必须审查完整 diff，确认未混入部署、密钥、生成物或用户无关改动。

## 7. 待项目维护者补录

正式团队化前必须补充：

- 角色到真实姓名/账号的映射；
- GitHub branch protection 与 required reviewers；
- CODEOWNERS；
- 生产值班表和升级路径；
- 安全事件联系方式；
- 发布审批人与替补人；
- 数据保护/删除请求责任人。
