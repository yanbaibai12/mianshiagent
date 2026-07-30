export const SAMPLE_RESUME_TITLE = '示例简历 - AI Agent 应用开发'

export const SAMPLE_RESUME_TEXT = `姓名：吴同学
求职意向：AI 大模型应用开发实习生
邮箱：candidate@example.com
电话：13800000000

教育背景
东华理工大学 软件工程 本科 2023.09-2027.06

专业技能
Python、FastAPI、React、TypeScript、SQL、MySQL、PostgreSQL、Redis、Git、Docker、RAG、Qdrant、BGE-M3、Agent、Function Calling

项目经历
面试简历 Agent 平台 后端与 AI 应用开发 2026.03-2026.07
- 负责 FastAPI 后端接口、简历解析、JD 定向优化、ATS 评分和面试报告生成链路。
- 使用 Qdrant 建设知识库和简历证据索引，接入 BGE-M3 embedding，支持关键词召回、向量召回和 RRF 融合排序。
- 接入 Redis/RQ 处理 JD 优化等长任务，前端通过任务状态接口展示 queued、running、success、failed 进度。
- 设计面试题生成逻辑，按项目、实习和 Agent 八股分组生成问题，避免只围绕单一经历出题。

智能知识库问答项目 开发负责人 2025.10-2026.01
- 完成文档清洗、递归切片、embedding 向量化和相似度检索，实现基于 RAG 的问答原型。
- 针对召回不稳定问题，补充关键词检索和重排策略，并用 20 组问题做召回回归评测。
- 使用 React 实现问答页面、来源引用展示、loading/error 状态和结果反馈。

实习经历
某科技公司 后端开发实习生 2025.07-2025.10
- 参与用户中心接口开发，负责登录注册、权限校验、异常返回和接口联调。
- 使用 Redis 缓存热点配置，排查缓存穿透和接口响应慢问题。
- 编写 SQL 查询和接口日志，协助定位线上错误并输出复盘记录。

自我评价
具备 Python 后端、RAG 应用、Agent 工具调用和前后端联调经验，能围绕需求拆解、工程实现、问题排查和结果交付进行复盘。`

export const SAMPLE_JOB_TITLE = 'AI Agent 应用开发实习生'

export const SAMPLE_COMPANY = '示例科技'

export const SAMPLE_JD_TEXT = `岗位职责：
1. 参与 AI Agent、RAG 问答、简历优化和面试训练等大模型应用功能开发。
2. 使用 Python、FastAPI 开发后端接口，完成任务队列、日志、权限和数据存储相关模块。
3. 参与 React 前端联调，优化用户操作流程、loading 状态和结果展示体验。
4. 参与知识库数据清洗、递归切片、embedding 向量化、Qdrant 索引构建和检索效果评测。

任职要求：
1. 熟悉 Python、FastAPI、SQL，了解 MySQL 或 PostgreSQL。
2. 了解 Redis、异步任务队列、接口幂等和失败重试。
3. 有 RAG、Agent、Function Calling、Embedding 或向量数据库实践经验。
4. 熟悉 Git，有良好的问题拆解、联调排查、结果交付和复盘能力。
5. 加分项：了解 BGE-M3、reranker、RRF 融合排序、Prompt Injection 防护。`
