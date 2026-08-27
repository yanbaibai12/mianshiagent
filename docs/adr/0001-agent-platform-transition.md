# ADR-0001：从固定 LLM 工作流迁移到 Agent Platform

- 状态：Proposed
- 编制日期：2026-08-27
- 生效条件：项目维护者批准
- 决策者：项目维护者
- 影响范围：后端架构、前端交互、数据模型、异步任务、Prompt、MCP、Skills、测试和发布流程

## 背景

当前系统以 FastAPI 路由和服务函数固定编排简历解析、JD 适配、面试生成、评分和报告。模型主要执行内容生成，系统缺少统一的 Agent Run、Step、Handoff、Tool Policy、Checkpoint、Budget 和 Trace。

项目后续重点从支付、公司管理、组织和运营后台转向：

- Agent Harness；
- MCP 工具；
- 版本化 Skills；
- 多 Agent 管理；
- 可恢复执行；
- Agent Eval；
- 有证据约束的简历改写。

## 决策

项目采用“**应用拥有的薄 Harness + 可替换模型/Agent SDK Adapter + MCP Tool Gateway**”架构。

具体含义：

1. 业务状态机、预算、权限、幂等、checkpoint、审计和质量门由本项目控制；
2. 不从零实现模型协议、流式响应和基础 Tool Calling；这些能力通过 provider adapter 接入成熟 SDK；
3. Agent SDK 不能直接获得数据库和高权限服务访问，所有业务工具通过 MCP Gateway 或受控 domain adapter；
4. Skill、Agent Definition、Prompt 和 Tool Contract 独立版本化；
5. 核心领域模型不依赖某个单一模型供应商；
6. 多 Agent 只用于需要判断、规划、动态追问和专业评审的环节；
7. PDF/DOCX 解析、数据库操作、导出、Schema 校验、事实规则等继续使用确定性代码。

## 原因

### 相比完全自研 Agent Runtime

优点：

- 减少模型协议和 Tool Calling 基础错误；
- 更容易跟随供应商能力演进；
- 团队可以聚焦业务状态、权限和质量。

### 相比完全依赖第三方 Agent 框架

优点：

- 数据、审计、幂等和恢复语义由项目控制；
- 不将核心业务状态隐藏在框架内存中；
- 可以替换 SDK 和模型；
- 更容易执行企业级安全和质量门。

## 备选方案

### A. 保持现有固定工作流

优点：简单、稳定、成本可控。
缺点：无法体现 Agent 的动态规划、工具选择、handoff 和恢复能力。
结论：保留为安全 fallback，但不作为目标架构。

### B. 完全自研 Harness 和模型循环

优点：控制力最高。
缺点：重复实现大量通用能力，测试和安全成本过高。
结论：不采用。

### C. 完全交给第三方多 Agent 框架

优点：开发速度快。
缺点：权限、状态、可恢复性和审计语义容易被框架限制。
结论：不采用；只通过 Adapter 使用其成熟能力。

## 结果

### 正面

- Agent 编排和业务状态边界清晰；
- 工具权限可以统一治理；
- 支持模型和 SDK 替换；
- 支持企业级 trace、eval 和回放；
- 旧固定工作流可以作为降级路径。

### 负面

- 需要新增 Run/Step/Event/Tool Call 等数据模型；
- 需要建立 MCP Gateway、Skill Registry 和 Eval 基础设施；
- 初期代码量和测试量上升；
- 多 Agent 会增加延迟和 token 成本；
- 团队必须维护明确的版本和兼容策略。

## 约束

- 未通过质量门的 Agent 路径不得替换现有稳定路径；
- 外部写操作默认需要批准；
- 所有高敏数据工具调用必须审计；
- 多 Agent 必须通过对照评测证明质量增益；
- 简历改写必须遵守 Claim/Evidence 事实约束；
- 不允许将模型内部自由文本作为唯一持久化状态。

## 验证计划

Phase 2 完成前必须证明：

1. Run 可持久化；
2. worker 崩溃可恢复；
3. 重复请求幂等；
4. 工具权限 fail-closed；
5. Trace 完整；
6. SDK Adapter 可以被测试替身替换；
7. 固定工作流 fallback 仍可用。

Phase 4 完成前必须证明：

1. 多 Agent 在目标评测集上优于固定工作流；
2. 质量增益足以覆盖成本和延迟增加；
3. 不出现循环失控、重复 Tool Call 和越权 handoff；
4. 动态追问相对批量出题有可测量提升。

## 后续 ADR

- ADR-0002：Phase 1A 产品表面退役与兼容边界（Accepted）；
- ADR-0003：Agent SDK/模型 Provider 选择；
- ADR-0004：MCP Server 部署边界；
- ADR-0005：Agent Run 事件模型和持久化；
- ADR-0006：认证、审批和 Tool Authorization；
- ADR-0007：简历 Evidence Graph；
- ADR-0008：Eval Judge 和人工评测流程。
