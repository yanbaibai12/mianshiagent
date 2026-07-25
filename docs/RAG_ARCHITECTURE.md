# RAG 知识库架构

## 当前实现

当前版本已经加入轻量 RAG，不依赖外部向量库或 embedding 服务。

组成：

- `knowledge_documents`：知识文档元数据。
- `knowledge_chunks`：知识片段，保存内容、关键词、分类。
- `KnowledgeBaseService`：关键词检索、片段打分、RAG 上下文拼装。
- `/api/knowledge/stats`：知识库统计。
- `/api/knowledge/search`：知识库检索。
- `/api/system/status`：返回 RAG 是否启用、文档数、片段数、检索方式。

当前内置知识覆盖：

- 技术岗项目面试评分标准。
- 后端岗位核心能力模型。
- 前端岗位核心能力模型。
- 产品岗位核心能力模型。
- 运营岗位核心能力模型。
- 简历表达优化规则。
- 面试报告改进建议规则。

## 已接入的业务链路

1. 简历模板优化
   - 检索 `resume_writing`、`job_knowledge`。
   - 作为表达规则和岗位能力参考。

2. JD 定向完善
   - 检索 `resume_writing`、`job_knowledge`。
   - 辅助识别岗位关键词、薄弱项和真实性边界。

3. 面试出题
   - 检索 `interview_rubric`、`job_knowledge`。
   - 让题目更贴近岗位能力和真实追问方式。

4. 作答评分
   - 检索 `interview_rubric`、`job_knowledge`、`reporting`。
   - 让评分更稳定，反馈更具体。

5. 面试报告
   - 检索 `interview_rubric`、`reporting`、`job_knowledge`。
   - 让薄弱点和复习建议更可执行。

## 安全边界

1. 当前 RAG 只存内置公共知识，不把用户简历写入全局知识库。
2. 用户简历、JD、作答记录只作为当前请求检索 query，不落入公共知识库。
3. 后续如果支持用户私有知识库，必须增加 `user_id` / `tenant_id` 并在检索时强制过滤。
4. 用户删除数据时，必须同步删除对应 chunk 和 embedding。
5. RAG 上下文只作为参考，Prompt 明确要求不得虚构经历、技能或数据。

## 为什么先不用向量库

当前环境依赖安装不稳定，MVP 优先保证可运行。轻量关键词检索的优势：

- 无新依赖。
- SQLite/PostgreSQL 都可跑。
- 对岗位、技能、题型这类明确关键词场景足够有效。
- 后续可以平滑替换检索实现，不影响业务路由。

## 下一阶段升级

### Phase 1：当前版本

- 数据库文本存储。
- 关键词检索。
- 内置知识库。

### Phase 2：可收费版本

- PostgreSQL + pgvector。
- embedding 模型配置。
- chunk 自动切分。
- Prompt 版本和 RAG 命中日志。
- 检索命中率和用户满意度统计。

### Phase 3：企业版

- 租户级知识库。
- 机构自定义题库。
- 私有化部署向量索引。
- 管理后台维护知识。
- 知识版本发布与回滚。

## 验收标准

1. `/api/system/status` 能看到 RAG 文档数和片段数。
2. `/api/knowledge/search` 输入 `Redis 后端 面试` 能召回后端/Redis/评分标准相关片段。
3. 简历优化后的 `optimized_data.rag_references` 有命中来源。
4. JD 适配响应包含 `rag_references`。
5. 完整面试链路仍能生成题目、评分和报告。
