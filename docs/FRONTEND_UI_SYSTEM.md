# 前端 UI 与维护说明

> 状态：Active
> 更新日期：2026-08-27
> 产品边界：Agent Platform v2

## 当前定位

前端是求职训练工作台，不是营销页、支付页、租户后台或运营后台。首屏围绕简历、岗位、面试、报告和训练计划展开。

## 设计原则

1. 工具型界面优先，保持稳定的信息架构和可重复操作效率。
2. 统一使用 `AppShell` 承载导航、品牌、用户入口和页面标题。
3. 基础按钮、卡片、字段、徽标、空状态和加载态集中复用。
4. 页面仅编排业务交互，避免复制设计系统样式。
5. 移动端保留关键任务路径，不隐藏取消、重试和错误信息。
6. AI 输出必须显示来源、状态和可回滚边界，不以动画掩盖不确定性。

## 关键文件

- `src/components/AppShell.tsx`：应用外壳、侧栏、移动导航、用户退出。
- `src/components/ui.tsx`：基础 UI 组件。
- `src/index.css`：设计系统样式和 Tailwind component layer。
- `src/pages/ResumeList.tsx`：工作台、上传、历史面试和简历列表。
- `src/pages/ResumeDetail.tsx`：简历优化、JD 适配、RAG 来源和结构化编辑。
- `src/pages/Interview.tsx`：题目导航、作答和评分。
- `src/pages/Report.tsx`：报告总览、维度得分、薄弱点、建议和导出。

## 已退役产品表面

以下入口不得恢复，除非有新的 Accepted ADR：

- 支付、套餐、升级和权益；
- 组织/公司管理；
- 系统运营后台；
- 面向用户的通用质量反馈。

## 后续 UI 计划

1. 简历改写增加 `before / after / evidence` 对照、Claim ID、来源行号和回滚。
2. 增加用户接受/拒绝/编辑记录，为人工评测提供真实行为证据。
3. 在生产持久化完成后建设 Run Inspector，展示状态、步骤、预算、Tool 名称和通用错误码；不得展示原始内部 state、完整 Tool Result、Token 或跨用户资源信息。
4. 增加异常、取消、重试、授权和跨浏览器测试。
5. Agent Shadow API 默认不在产品 UI 中展示，仅供内部评测。
