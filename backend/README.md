# 面试简历 Agent 后端

基于 FastAPI + SQLAlchemy 的简历优化与模拟面试系统。MVP 默认使用本地 SQLite 和 `LLM_PROVIDER=local`，无需先准备 PostgreSQL 或外部 LLM Key。

## 快速开始

### 1. 安装依赖

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 默认即可本地运行；接入真实模型时再编辑 LLM 配置
```

### 3. 启动服务

```bash
uvicorn app.main:app --reload
```

启动后访问：

- API: http://127.0.0.1:8000
- Docs: http://127.0.0.1:8000/docs

## LLM 配置说明

支持通过环境变量切换不同模型：

```bash
# Local MVP fallback
LLM_PROVIDER=local

# OpenAI
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
LLM_API_KEY=<OPENAI_API_KEY>

# Kimi (Moonshot)
LLM_PROVIDER=moonshot
LLM_MODEL=moonshot-v1-8k
LLM_API_KEY=<MOONSHOT_API_KEY>
LLM_BASE_URL=https://api.moonshot.cn/v1

# DeepSeek
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
LLM_API_KEY=<DEEPSEEK_API_KEY>
LLM_BASE_URL=https://api.deepseek.com/v1

# Claude
LLM_PROVIDER=anthropic
LLM_MODEL=claude-3-5-sonnet-20241022
LLM_API_KEY=<ANTHROPIC_API_KEY>
```
