# 面试简历 Agent — 产品需求文档（PRD v1.0）

> 文档版本：v1.0  
> 更新日期：2026-07-22  
> 产品形态：Web 端（MVP）  
> 后端技术栈：Python + FastAPI  
> 前端技术栈：React 18 + TailwindCSS + Zustand

---

## 1. 项目背景与目标

### 1.1 背景

求职者在准备面试时通常面临两个问题：

1. **简历不会写**：表达不精炼、亮点不突出、与岗位 JD 匹配度低。
2. **面试准备不足**：对自己简历上的项目和实习经历缺乏系统梳理，回答问题没有章法。

### 1.2 目标

构建一个 AI Agent，提供两大核心能力：

1. **简历优化能力**：基于平台提供的模板优化简历，并能根据目标岗位 JD 进一步定向完善。
2. **模拟面试能力**：基于用户简历上的项目/实习要点自动出题，用户作答后由 Agent 评分并给出精简参考答案，最终输出面试总结报告。

---

## 2. 用户与使用流程

### 2.1 核心用户

- 准备求职的应届生、实习生、初级社招人员。
- 使用场景：投递前优化简历、面试前模拟演练。

### 2.2 MVP 主流程

```
1. 登录账号
   └── 2. 上传简历（PDF / DOCX / 粘贴文本）
        └── 3. 解析为结构化数据
             ├── 4a. 简历优化（基于内置模板）
             ├── 4b. JD 定向完善（可选）
             └── 5. 保存优化后的简历
                  └── 6. 选择简历开始模拟面试
                       ├── 7. 自动抽取要点 + 每点 5 题
                       ├── 8. 用户文字作答
                       ├── 9. AI 评分 + 精简答案（同页展示）
                       └── 10. 生成面试总结报告
```

---

## 3. 技术方案

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                        前端 Web 端                           │
│              React 18 + TailwindCSS + Zustand                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                        后端服务                              │
│                    Python 3.11+ / FastAPI                    │
│  ┌─────────────┐ ┌─────────────┐ ┌───────────────────────┐  │
│  │  用户认证    │ │  简历模块    │ │      面试模块          │  │
│  │  Auth API   │ │ Resume API  │ │  Interview API        │  │
│  └─────────────┘ └─────────────┘ └───────────────────────┘  │
│  ┌─────────────┐ ┌─────────────┐ ┌───────────────────────┐  │
│  │  文件解析    │ │  LLM 编排    │ │     历史记录           │  │
│  │  PyMuPDF    │ │  OpenAI SDK │ │  History API          │  │
│  │ python-docx │ │ /Anthropic  │ │                       │  │
│  └─────────────┘ └─────────────┘ └───────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      数据层 & 外部服务                        │
│   PostgreSQL  +  Redis  +  对象存储（简历文件）                │
│   LLM API（Claude / OpenAI / 国产，由平台统一配置密钥）        │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 技术栈

| 层级 | 选型 | 说明 |
|---|---|---|
| 前端 | React 18 + TailwindCSS + Zustand | 轻量、现代、易上手 |
| 后端 | FastAPI (Python 3.11+) | 异步高性能、类型提示、自动生成 API 文档 |
| 数据库 | PostgreSQL 16+ | 关系型 + JSONB 灵活字段 |
| ORM | SQLAlchemy 2.0 + Alembic | 迁移管理成熟 |
| 缓存/队列 | Redis + Celery（可选） | 会话缓存、异步任务、限流 |
| 文件存储 | 本地/MinIO/云 OSS | 存储 PDF/DOCX |
| PDF 解析 | PyMuPDF / pdfplumber | 提取文本效果较好 |
| DOCX 解析 | python-docx | 标准方案 |
| LLM SDK | anthropic / openai / httpx | 统一封装多模型调用 |
| 多模型兼容 | 配置化切换 provider + model | 支持 GPT、Kimi、DeepSeek、Claude 等主流模型 |
| 部署 | Docker + Nginx + Gunicorn | 容器化 + 生产级 WSGI 服务器 |

### 3.3 后端项目目录结构

```
backend/
├── app/
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # 配置管理
│   ├── dependencies.py         # 依赖注入
│   ├── routers/
│   │   ├── auth.py
│   │   ├── resumes.py
│   │   ├── templates.py
│   │   └── interviews.py
│   ├── services/
│   │   ├── auth_service.py
│   │   ├── resume_parser.py
│   │   ├── resume_optimizer.py
│   │   ├── jd_adapter.py
│   │   ├── interview_service.py
│   │   └── llm_client.py       # 统一封装多模型调用
│   ├── models/
│   │   ├── user.py
│   │   ├── resume.py
│   │   ├── template.py
│   │   └── interview.py
│   ├── schemas/
│   │   ├── auth.py
│   │   ├── resume.py
│   │   ├── template.py
│   │   └── interview.py
│   ├── prompts/
│   │   ├── parse_resume.py
│   │   ├── optimize_resume.py
│   │   ├── adapt_jd.py
│   │   ├── generate_questions.py
│   │   ├── score_answer.py
│   │   └── summarize_interview.py
│   └── utils/
│       ├── security.py
│       ├── storage.py
│       └── json_extract.py
├── alembic/                    # 数据库迁移
├── tests/
├── requirements.txt
├── Dockerfile
└── .env.example
```

### 3.4 LLM 客户端设计（多模型兼容）

LLM 统一调用层必须具备多模型兼容性，支持以下模型：

- OpenAI GPT 系列（gpt-3.5-turbo / gpt-4 / gpt-4o 等）
- Kimi（Moonshot）
- DeepSeek
- Anthropic Claude 系列
- 其他兼容 OpenAI 接口格式的国产或自研模型

切换方式：修改环境变量，无需改动业务代码。

```bash
LLM_PROVIDER=openai        # anthropic / openai / moonshot / deepseek / custom
LLM_MODEL=gpt-4o
LLM_API_KEY=<LLM_API_KEY>
LLM_BASE_URL=              # 国产模型通常需要自定义 base_url
```

统一封装要求：

- 请求参数标准化（system / user 消息、temperature、max_tokens）
- 响应格式统一返回字符串，供业务层使用
- JSON 输出采用统一后处理提取，不依赖模型的原生 JSON mode
- 失败时自动重试 2 次，并返回友好错误信息
- 新增模型时只需在 `llm_client.py` 中增加 provider 分支，业务代码零改动

示例代码：

```python
import os
import json
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL")

async def chat_completion(
    messages: list[dict],
    temperature: float = 0.3,
    max_tokens: int = 4000,
) -> str:
    # Anthropic Claude
    if LLM_PROVIDER == "anthropic":
        client = AsyncAnthropic(api_key=LLM_API_KEY)
        system = ""
        user_messages = messages
        if messages and messages[0]["role"] == "system":
            system = messages[0]["content"]
            user_messages = messages[1:]
        response = await client.messages.create(
            model=LLM_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=user_messages,
        )
        return response.content[0].text

    # OpenAI 兼容接口：OpenAI / Moonshot / DeepSeek / 其他国产模型
    elif LLM_PROVIDER in ("openai", "moonshot", "deepseek", "custom"):
        client = AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL or None)
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    else:
        raise ValueError(f"Unsupported provider: {LLM_PROVIDER}")


def extract_json(text: str) -> dict:
    """从 LLM 输出中安全提取 JSON"""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return json.loads(text.strip())
```

### 3.5 文件解析服务示例

```python
import fitz  # PyMuPDF
from docx import Document

class ResumeParser:
    @staticmethod
    def parse_pdf(file_path: str) -> str:
        text = ""
        with fitz.open(file_path) as doc:
            for page in doc:
                text += page.get_text()
        return text.strip()

    @staticmethod
    def parse_docx(file_path: str) -> str:
        doc = Document(file_path)
        return "\n".join([p.text for p in doc.paragraphs]).strip()
```

---

## 4. 功能需求

### 4.1 用户登录

| 编号 | 需求项 | 详细说明 |
|---|---|---|
| U1.1 | 登录方式 | MVP 支持邮箱 + 密码登录 |
| U1.2 | 注册 | 用户通过邮箱注册账号，密码需加密存储 |
| U1.3 | JWT 鉴权 | 登录后返回 JWT Token，后续请求携带 Token 鉴权 |
| U1.4 | 密码安全 | 密码使用 bcrypt 加密，不存储明文 |
| U1.5 | API 密钥状态 | API 密钥由平台统一配置。若密钥未配置、失效或余额不足，用户点击 AI 功能时提示。LLM 统一调用层必须具备多模型兼容性。通过配置化的方式支持以下模型：OpenAI GPT 系列、Kimi（Moonshot）、DeepSeek、Anthropic Claude 系列，以及其他兼容 OpenAI 接口格式的国产或自研模型。切换方式：修改环境变量 `LLM_PROVIDER`、`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`，无需改动业务代码。统一封装要求：请求参数标准化；响应格式统一返回字符串；JSON 输出采用统一后处理提取；失败时自动重试 2 次；新增模型时只需在 `llm_client.py` 中增加 provider 分支，业务代码零改动。 |

### 4.2 简历上传与解析

| 编号 | 需求项 | 详细说明 |
|---|---|---|
| R1.1 | 上传格式 | 支持 PDF、DOCX 文件上传；同时保留纯文本/Markdown 粘贴入口作为兜底 |
| R1.2 | 文件大小 | 单个文件大小限制 ≤ 10MB |
| R1.3 | 信息结构化解析 | 将简历解析为：个人信息、教育背景、工作经历、项目经历、技能、自我评价 |
| R1.4 | 可面试要点识别 | 从项目/实习经历中提取可面试要点，每个经历至少识别 1 个要点 |
| R1.5 | 解析预览 | 解析后以表单/卡片形式展示结构化内容，允许用户手动修正 |
| R1.6 | 解析失败兜底 | PDF/DOCX 解析失败时，提示用户可粘贴纯文本手动输入 |

### 4.3 模板驱动的简历优化

| 编号 | 需求项 | 详细说明 |
|---|---|---|
| R2.1 | 模板来源 | 模板由平台提供，MVP 内置 3-5 个模板：技术岗、产品岗、运营岗、通用模板 |
| R2.2 | 模板定义 | 每个模板包含：模块顺序、各模块撰写规则、表达风格、鼓励使用的关键词/句式 |
| R2.3 | AI 优化 | Agent 按选定模板对用户简历进行改写：重组结构、提炼亮点、量化成果、优化措辞 |
| R2.4 | 可编辑输出 | 优化结果按段落展示，用户可逐段编辑、接受、拒绝、要求"再优化一次" |
| R2.5 | 保存简历 | 用户可保存优化后的简历到"我的简历"列表，支持命名区分 |

### 4.4 基于 JD 的简历定向完善

| 编号 | 需求项 | 详细说明 |
|---|---|---|
| R3.1 | JD 输入 | 仅支持粘贴 JD 纯文本（MVP 不上传图片） |
| R3.2 | JD 解析 | 提取岗位职责、必备技能、加分项、关键词 |
| R3.3 | 匹配度分析 | 对比简历与 JD，给出匹配度评分及薄弱项提示 |
| R3.4 | 定向改写 | 针对薄弱模块，自动调整措辞、补充 JD 关键词、突出相关经历 |
| R3.5 | 真实性约束 | AI 不得虚构经历、技能或数据，只能做表达重组与重点调整 |
| R3.6 | 一键应用 | 用户可一键应用 JD 完善结果，或逐段查看修改建议后选择性采纳 |

### 4.5 模拟面试

#### 4.5.1 面试准备

| 编号 | 需求项 | 详细说明 |
|---|---|---|
| I1.1 | 选择简历 | 从"我的简历"中选择一份已保存的简历开始面试 |
| I1.2 | 关联 JD（可选） | 可选择关联一个 JD，面试问题会结合 JD 偏好出题；不关联则 purely 基于简历出题 |
| I1.3 | 交互方式 | MVP 仅支持文字回答 |

#### 4.5.2 自动抽点与出题

| 编号 | 需求项 | 详细说明 |
|---|---|---|
| I2.1 | 要点识别 | 自动识别简历中每个项目/实习的可面试要点 |
| I2.2 | 每要点 5 题 | 每个要点生成 5 个递进式小问题，覆盖：背景、技术细节、决策原因、困难与解决、成果与反思 |
| I2.3 | 问题分组 | 按"项目/实习 → 要点 → 5 题"三级结构展示 |
| I2.4 | 题目数量 | 用户可查看全部题目，但逐题作答 |
| I2.5 | 题目质量 | 每道题必须基于简历原文，不得引入用户未提及的技能或经历 |

#### 4.5.3 作答、评分与精简答案

| 编号 | 需求项 | 详细说明 |
|---|---|---|
| I3.1 | 文字作答 | 用户针对当前题目在输入框中提交文字回答 |
| I3.2 | AI 评分 | 从 5 个维度评分（1-10 分）：完整性、逻辑清晰度、与简历一致性、表达精炼度、技术/业务深度 |
| I3.3 | 评分展示 | 评分与评语在同一题页面直接展示 |
| I3.4 | 精简答案 | 在同一题页面展示"面试可背诵版"精简答案，控制在 100-200 字，突出结构和关键词 |
| I3.5 | 追问/换题 | 用户可要求"换一种问法"重新出题，或"进一步追问" |
| I3.6 | 作答保存 | 每道题作答后自动保存，支持中途退出后回来继续 |

### 4.6 面试总结报告

| 编号 | 需求项 | 详细说明 |
|---|---|---|
| S1.1 | 触发条件 | 用户完成至少 3 道题后，可生成总结报告 |
| S1.2 | 总体评分 | 展示本次面试总体得分（百分制或 10 分制） |
| S1.3 | 分项雷达图 | 展示 5 个维度的分项得分 |
| S1.4 | 表现总结 | 总结用户回答的共性优点与不足 |
| S1.5 | 薄弱点清单 | 列出 3-5 个需要重点准备的薄弱点 |
| S1.6 | 推荐复习方向 | 给出具体建议，如"补充 xx 技术原理"、"准备量化成果表述" |
| S1.7 | 历史记录 | 每次面试记录保存在"历史记录"中，用户可随时查看过往报告 |
| S1.8 | 报告导出 | MVP 支持导出 Markdown 格式，PDF 导出可作为二期 |

### 4.7 历史记录与数据管理

| 编号 | 需求项 | 详细说明 |
|---|---|---|
| H1.1 | 我的简历 | 列表展示用户上传/优化过的所有简历，支持重命名、删除、设为默认 |
| H1.2 | 历史面试 | 列表展示每次模拟面试的时间、关联简历、总体得分、操作（查看报告/继续作答/删除） |
| H1.3 | 数据隔离 | 用户只能看到和编辑自己的简历与面试记录 |

---

## 5. 数据模型设计

### 5.1 用户表 users

```sql
CREATE TABLE users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email         VARCHAR(255) UNIQUE NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  nickname      VARCHAR(100),
  created_at    TIMESTAMP DEFAULT NOW(),
  updated_at    TIMESTAMP DEFAULT NOW()
);
```

### 5.2 系统配置表 system_configs

```sql
CREATE TABLE system_configs (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  key         VARCHAR(100) UNIQUE NOT NULL,
  value       TEXT NOT NULL,
  encrypted   BOOLEAN DEFAULT TRUE,
  updated_at  TIMESTAMP DEFAULT NOW()
);
```

### 5.3 简历表 resumes

```sql
CREATE TABLE resumes (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
  title           VARCHAR(200) NOT NULL,
  original_file   VARCHAR(500),
  original_text   TEXT,
  parsed_data     JSONB,
  optimized_data  JSONB,
  jd_text         TEXT,
  match_score     NUMERIC(5,2),
  template_id     VARCHAR(50),
  is_default      BOOLEAN DEFAULT FALSE,
  created_at      TIMESTAMP DEFAULT NOW(),
  updated_at      TIMESTAMP DEFAULT NOW()
);
```

parsed_data 示例结构：

```json
{
  "personal": { "name": "", "phone": "", "email": "" },
  "education": [
    { "school": "", "major": "", "degree": "", "time": "" }
  ],
  "experience": [
    {
      "company": "",
      "role": "",
      "time": "",
      "highlights": ["", ""],
      "interview_points": [
        { "id": "p1", "title": "微服务拆分", "description": "..." }
      ]
    }
  ],
  "projects": [
    {
      "name": "",
      "role": "",
      "time": "",
      "description": "",
      "tech_stack": [],
      "interview_points": [
        { "id": "p2", "title": "高并发优化", "description": "..." }
      ]
    }
  ],
  "skills": ["", ""],
  "summary": ""
}
```

### 5.4 模板表 resume_templates

```sql
CREATE TABLE resume_templates (
  id          VARCHAR(50) PRIMARY KEY,
  name        VARCHAR(100) NOT NULL,
  category    VARCHAR(50),
  structure   JSONB NOT NULL,
  prompt      TEXT NOT NULL,
  is_builtin  BOOLEAN DEFAULT TRUE,
  created_at  TIMESTAMP DEFAULT NOW()
);
```

### 5.5 面试会话表 interviews

```sql
CREATE TABLE interviews (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
  resume_id       UUID REFERENCES resumes(id) ON DELETE SET NULL,
  jd_text         TEXT,
  status          VARCHAR(20) DEFAULT 'ongoing',
  total_score     NUMERIC(5,2),
  dimension_scores JSONB,
  summary         TEXT,
  weak_points     JSONB,
  suggestions     JSONB,
  created_at      TIMESTAMP DEFAULT NOW(),
  updated_at      TIMESTAMP DEFAULT NOW()
);
```

### 5.6 面试题目与作答表 interview_questions

```sql
CREATE TABLE interview_questions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  interview_id    UUID REFERENCES interviews(id) ON DELETE CASCADE,
  resume_point_id VARCHAR(50),
  point_title     VARCHAR(200),
  sequence        INT NOT NULL,
  question        TEXT NOT NULL,
  user_answer     TEXT,
  scores          JSONB,
  total_score     NUMERIC(5,2),
  feedback        TEXT,
  refined_answer  TEXT,
  answered_at     TIMESTAMP,
  created_at      TIMESTAMP DEFAULT NOW()
);
```

scores 示例：

```json
{
  "completeness": 8,
  "logic": 7,
  "consistency": 9,
  "conciseness": 6,
  "depth": 7
}
```

---

## 6. API 接口设计

### 6.1 认证相关

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/auth/register | 邮箱注册 |
| POST | /api/auth/login | 邮箱登录，返回 JWT |
| POST | /api/auth/logout | 登出 |
| GET  | /api/auth/me | 获取当前用户信息 |

### 6.2 简历相关

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/resumes/upload | 上传简历文件或文本 |
| GET  | /api/resumes | 获取我的简历列表 |
| GET  | /api/resumes/:id | 获取简历详情 |
| PUT  | /api/resumes/:id | 更新简历解析后的结构化内容 |
| DELETE | /api/resumes/:id | 删除简历 |
| POST | /api/resumes/:id/optimize | 基于模板优化简历 |
| POST | /api/resumes/:id/adapt-jd | 基于 JD 定向完善 |
| POST | /api/resumes/:id/save-optimized | 保存优化后的版本 |

### 6.3 模板相关

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/templates | 获取简历模板列表 |
| GET | /api/templates/:id | 获取模板详情 |

### 6.4 面试相关

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/interviews | 创建面试会话 |
| GET  | /api/interviews | 获取历史面试列表 |
| GET  | /api/interviews/:id | 获取面试会话详情 |
| POST | /api/interviews/:id/generate-questions | 基于简历生成题目 |
| GET  | /api/interviews/:id/questions | 获取题目列表 |
| POST | /api/interviews/:id/questions/:qid/answer | 提交作答并获取评分和精简答案 |
| POST | /api/interviews/:id/regenerate-question | 换一种问法 / 追问 |
| POST | /api/interviews/:id/finish | 结束面试，生成总结报告 |
| GET  | /api/interviews/:id/report | 获取面试总结报告 |
| GET  | /api/interviews/:id/report/export | 导出 Markdown 报告 |

---

## 7. 核心 Prompt 设计规范

### 7.1 简历解析 Prompt

```
你是一位专业的简历解析助手。请从以下简历文本中提取结构化信息，输出 JSON：

1. personal: 姓名、电话、邮箱、求职意向
2. education: 学校、专业、学历、时间
3. experience: 工作经历，每项包含公司、职位、时间、亮点、可面试要点
4. projects: 项目经历，每项包含项目名、角色、时间、描述、技术栈、可面试要点
5. skills: 技能列表
6. summary: 自我评价

可面试要点指：面试官可能围绕该经历提问的具体技术点、业务难点、成果数据或决策过程。
每个项目/实习至少提取 1 个可面试要点。

简历文本：
{resume_text}
```

### 7.2 模板优化 Prompt

```
你是一位资深 HR 和求职顾问。请根据以下【简历模板】的规则，优化用户的简历内容。

模板规则：
{template_rules}

原始简历：
{resume_data}

要求：
1. 严格遵循模板的模块顺序和风格
2. 使用 STAR 法则描述经历
3. 尽量量化成果，如用户数、QPS、转化率、营收等
4. 突出技术深度和业务价值
5. 语言精炼，每段不超过 3 行
6. 不要虚构用户没有的经历或数据

请输出优化后的完整简历，按模块展示。
```

### 7.3 JD 定向完善 Prompt

```
你是一位岗位匹配专家。请根据以下岗位 JD，分析简历匹配度并给出优化建议。

岗位 JD：
{jd_text}

当前简历：
{resume_data}

请完成：
1. 提取 JD 核心要求（职责、必备技能、加分项、关键词）
2. 分析简历与 JD 的匹配度，指出缺失或薄弱项
3. 针对薄弱项，定向改写相关经历，突出 JD 关键词
4. 输出匹配度评分（0-100）和优化后的简历

约束：
- 不得虚构经历、技能或数据
- 仅做表达重组和重点调整
```

### 7.4 面试要点出题 Prompt

```
你是一位技术/业务面试官。请基于以下简历要点，生成 5 个递进式面试小问题。

要点：
{point_title}
要点描述：
{point_description}
关联经历：
{experience_context}

要求：
1. 5 个问题覆盖：背景、技术细节、决策原因、困难与解决、成果与反思
2. 问题必须基于简历原文，不得引入用户未提及的技能
3. 问题具体、有针对性，避免泛泛而谈
4. 输出 JSON 数组，每个元素包含 question_id 和 question_text
```

### 7.5 作答评分与精简答案 Prompt

```
你是一位资深面试官。请根据以下题目和用户回答，给出评分和精简答案。

题目：
{question}

用户回答：
{answer}

简历上下文：
{resume_context}

请从以下 5 个维度评分（1-10 分）：
1. 完整性：是否回答了问题的核心
2. 逻辑清晰度：结构是否清楚
3. 与简历一致性：是否与简历描述一致
4. 表达精炼度：是否简洁不啰嗦
5. 技术/业务深度：是否有深度思考

输出 JSON：
{
  "scores": { "completeness": 8, "logic": 7, ... },
  "total_score": 7.5,
  "feedback": "优点：... 不足：...",
  "refined_answer": "100-200字的精简答案，包含STAR结构和关键词"
}
```

### 7.6 面试总结报告 Prompt

```
你是一位面试辅导专家。请根据以下用户的模拟面试作答记录，生成总结报告。

作答记录：
{questions_and_answers}

请输出：
1. 总体评分（0-100）
2. 五个维度的分项得分
3. 表现总结（优点 + 不足）
4. 3-5 个薄弱点清单
5. 具体的复习/准备建议

语言专业、鼓励性，但指出问题要直接。
```

---

## 8. 非功能需求

| 编号 | 类别 | 需求 |
|---|---|---|
| N1 | 响应性能 | 单题评分与精简答案生成 ≤ 15 秒；简历优化 ≤ 30 秒；面试报告 ≤ 20 秒 |
| N2 | 数据安全 | 用户简历、JD、作答记录仅用于当前服务，不用于模型训练 |
| N3 | 密钥安全 | API 密钥由平台统一配置，加密存储，不返回给前端 |
| N4 | 可解释性 | AI 修改建议、评分、参考答案需说明依据 |
| N5 | 容错性 | AI 调用失败时提示重试，已输入内容不丢失 |
| N6 | 多模型兼容 | LLM 客户端支持通过环境变量切换 GPT、Kimi、DeepSeek、Claude 等主流模型，新增模型时业务代码零改动 |
| N7 | 浏览器兼容 | 支持 Chrome、Edge、Safari 最新两个大版本 |

---

## 9. 验收标准

### 9.1 登录与密钥

| 验收项 | 标准 |
|---|---|
| 登录成功率 | 正常网络下登录成功率 ≥ 99% |
| 密钥不暴露 | 前端任何接口均不返回完整 API 密钥 |
| 失效提示 | 密钥失效或余额不足时，5 秒内给出明确提示 |

### 9.2 简历解析

| 验收项 | 标准 |
|---|---|
| 文件格式 | 成功解析 PDF 与 DOCX |
| 字段完整率 | 标准简历关键字段完整率 ≥ 85% |
| 要点识别 | 每个项目/实习至少识别 1 个可面试要点 |

### 9.3 简历优化

| 验收项 | 标准 |
|---|---|
| 模板符合度 | 输出简历结构符合选定模板 |
| 优化有效性 | 人工抽检 10 份，认为表达更精炼/亮点更突出的 ≥ 7 份 |
| 编辑功能 | 用户可逐段编辑、接受、拒绝、再优化 |

### 9.4 JD 定向完善

| 验收项 | 标准 |
|---|---|
| 关键词覆盖 | 完善后 JD 核心关键词出现率提升 ≥ 30% |
| 真实性 | 抽检 20 份，虚构经历/技能的样本数为 0 |
| 匹配度方向 | 系统匹配度评分与人工判断一致率 ≥ 80% |

### 9.5 模拟面试

| 验收项 | 标准 |
|---|---|
| 出题数量 | 每个要点生成 5 题，总数准确 |
| 题目质量 | 抽检 30 题，认为合理、基于简历的比例 ≥ 90% |
| 评分一致性 | 系统与人工评分差异 ≤ 2 分的比例 ≥ 75% |
| 答案质量 | 精简答案 ≤ 200 字且包含关键结构的比例 ≥ 80% |
| 展示方式 | 评分、评语、精简答案在同一题页面展示 |

### 9.6 报告与历史

| 验收项 | 标准 |
|---|---|
| 报告内容 | 包含总体评分、分项雷达图、表现总结、薄弱点、复习方向 |
| 总结准确性 | 人工判断报告总结与作答一致率 ≥ 80% |
| 历史记录 | 面试记录正确保存，支持查看和继续作答 |
| 报告导出 | 支持导出 Markdown |

### 9.7 多模型兼容性

| 验收项 | 标准 |
|---|---|
| 配置切换 | 仅修改环境变量即可切换 GPT / Kimi / DeepSeek / Claude，无需改动业务代码 |
| 接口一致性 | 同一套 Prompt 在不同模型下均能返回可用结果 |
| 失败重试 | 模型调用失败时自动重试 2 次，仍失败后返回友好提示 |
| 新增模型 | 新增一个兼容 OpenAI 接口的模型时，开发工作量 ≤ 30 分钟 |

---

## 10. 关键流程说明

### 10.1 简历优化流程

```
用户上传简历 → 解析为结构化数据 → 用户选择模板 → 调用优化 Prompt
    → 展示优化结果 → 用户编辑/采纳 → 保存到 resumes.optimized_data
```

### 10.2 JD 定向完善流程

```
用户选择简历 → 粘贴 JD → 提取 JD 关键词 → 匹配度分析 → 定向改写
    → 展示修改建议 → 用户一键应用 → 保存新版本
```

### 10.3 模拟面试流程

```
用户选择简历 → 创建 interview → 抽取要点 → 每要点生成 5 题
    → 用户逐题作答 → AI 实时评分 + 精简答案 → 完成至少 3 题后生成报告
```

---

## 11. 开发排期（MVP，建议 4-6 周）

| 阶段 | 周期 | 任务 |
|---|---|---|
| 第 1 周：基础搭建 | 5 天 | FastAPI 项目初始化、Alembic 迁移、用户认证、LLM 客户端封装、环境配置 |
| 第 2 周：简历解析 | 5 天 | PDF/DOCX 上传与解析、Resume CRUD、结构化数据编辑 |
| 第 3 周：AI 优化 | 5 天 | 模板管理、简历优化 Prompt、JD 解析与定向完善 |
| 第 4 周：面试模块 | 5 天 | 要点抽取、每点 5 题、作答评分、精简答案 |
| 第 5 周：报告与历史 | 5 天 | 面试总结报告、历史记录、Markdown 导出 |
| 第 6 周：联调验收 | 5 天 | 前后端联调、Prompt 调优、验收测试、Bug 修复 |

---

## 12. 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| LLM 输出不稳定 | 解析/优化/评分质量波动 | 加 JSON Schema 校验、失败重试、人工兜底编辑 |
| PDF/DOCX 解析格式混乱 | 结构化解析准确率下降 | 提供手动编辑入口；复杂格式建议粘贴文本 |
| API 密钥费用超支 | 成本不可控 | 加 Token 用量统计、限流、用户操作触发调用 |
| 题目与简历脱节 | 面试体验差 | 严格限制 Prompt：问题必须基于简历原文 |

---

## 13. 二期可扩展（本次不实现）

为后续迭代预留，但 MVP 不做：

- 语音面试输入
- 简历 PDF 导出
- 多轮追问与深度压力面
- 行为面 / HR 面题型
- 用户自定义上传模板
- 多语言简历
- 分享报告给导师/HR

---

## 14. 待确认事项

1. 前端框架是否确认使用 React？（Vue 也可替代）
2. 数据库是否确认使用 PostgreSQL？（MySQL 也可替代）
3. LLM 供应商是 Claude、OpenAI 还是国产模型？
4. 部署环境是本地 Docker、服务器还是云平台？
5. 是否需要短信验证码登录？MVP 先用邮箱密码是否足够？
