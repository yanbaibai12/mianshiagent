# 面试简历 Agent 前端

基于 React + Vite + TailwindCSS 的 Web 前端。

## 快速开始

```bash
cd frontend
npm install
npm run dev
```

如果 5173 端口已占用：

```bash
npm run dev -- --host 127.0.0.1 --port 5174
```

## 环境变量

```bash
cp .env.example .env
```

编辑 `.env`：

```
VITE_API_BASE_URL=http://localhost:8000
```

## 功能页面

- 登录/注册
- 简历列表与上传
- 简历优化
- JD 定向完善
- 模拟面试
- 面试报告
