# 前端 UI 与维护说明

## 当前定位

前端按企业级工作台方向改造，不做营销落地页。第一屏直接进入简历、面试、报告工作流。

## 设计原则

1. 工具型界面优先：信息密度适中，便于重复使用。
2. 页面结构稳定：统一使用 `AppShell` 承载导航、品牌、用户入口和页面标题。
3. 组件复用：按钮、卡片、字段、徽标、状态卡、空状态、加载态集中在 `src/components/ui.tsx`。
4. 页面只写业务逻辑：避免每个页面复制大量样式。
5. 移动端可用：小屏保留顶部导航和关键操作。

## 关键文件

- `src/components/AppShell.tsx`：应用外壳、侧栏、移动导航、用户退出。
- `src/components/ui.tsx`：基础 UI 组件。
- `src/index.css`：设计系统样式和 Tailwind component layer。
- `src/pages/ResumeList.tsx`：工作台、上传、系统状态、历史面试、简历列表。
- `src/pages/ResumeDetail.tsx`：简历优化、JD 适配、RAG 来源、JSON 编辑。
- `src/pages/Interview.tsx`：题目导航、作答、评分展示。
- `src/pages/Report.tsx`：报告总览、维度得分、薄弱点、建议、导出。

## 安全与健壮性改动

1. 升级 `vite`、`react-router-dom` 并引入 `lucide-react`。
2. `npm audit` 当前为 0 漏洞。
3. `auth` store 对 localStorage 用户 JSON 做容错解析，避免坏数据导致白屏。
4. 主要表单增加字符计数和前端 `maxLength`。
5. 上传、优化、JD 适配、评分等操作增加 loading/error 状态。

## 后续建议

1. 增加 Playwright 冒烟测试：登录、上传文本简历、优化、创建面试、提交答案、生成报告。
2. 把 JSON 编辑升级为结构化表单编辑。
3. 增加知识库管理页：检索、分类、命中测试、启停文档。
4. 增加支付/套餐状态入口。
5. 增加管理员后台和租户视图。
