from functools import lru_cache
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 数据库
    DATABASE_URL: str = "sqlite+aiosqlite:///./interview_agent.db"

    # JWT
    SECRET_KEY: str = "your-secret-key-here-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080

    # LLM
    LLM_PROVIDER: str = "local"  # local / openai / moonshot / deepseek / anthropic / custom
    LLM_MODEL: str = "gpt-4o"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str | None = None
    LLM_MAX_RETRIES: int = 2
    LLM_TIMEOUT_SECONDS: int = 60
    LLM_ALLOW_FALLBACK: bool = False
    LLM_INPUT_PRICE_PER_1K_TOKENS_CNY: float = 0
    LLM_OUTPUT_PRICE_PER_1K_TOKENS_CNY: float = 0

    # Embedding / vector knowledge base
    VECTOR_STORE_BACKEND: str = "qdrant"  # qdrant / keyword
    QDRANT_URL: str = ""
    QDRANT_LOCAL_PATH: str = "qdrant_storage"
    QDRANT_API_KEY: str = ""
    QDRANT_COLLECTION: str = "mianshiagent_knowledge_bge_m3"
    QDRANT_RESUME_COLLECTION: str = "mianshiagent_resume_bge_m3"
    QDRANT_VECTOR_SIZE: int = 1024
    QDRANT_TIMEOUT_SECONDS: float = 5.0
    QDRANT_SYNC_ON_STARTUP: bool = True
    RESUME_CHUNK_SIZE: int = 700
    RESUME_CHUNK_OVERLAP: int = 100

    EMBEDDING_PROVIDER: str = "bge_m3"  # bge_m3 / openai_compatible / hash
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_BASE_URL: str | None = None
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_TIMEOUT_SECONDS: int = 60
    EMBEDDING_BATCH_SIZE: int = 8
    EMBEDDING_MAX_LENGTH: int = 8192
    EMBEDDING_DEVICE: str = "cpu"
    EMBEDDING_CACHE_DIR: str = "models"
    EMBEDDING_HF_ENDPOINT: str = "https://hf-mirror.com"
    EMBEDDING_USE_FP16: bool = False
    EMBEDDING_ALLOW_FALLBACK: bool = False

    # Reranker. Disabled by default; set RERANK_PROVIDER=bge_reranker for local BGE rerank.
    RERANK_PROVIDER: str = "none"  # none / bge_reranker / remote
    RERANK_MODEL: str = "BAAI/bge-reranker-v2-m3"
    RERANK_BASE_URL: str | None = None
    RERANK_API_KEY: str = ""
    RERANK_TOP_K: int = 20
    RERANK_BATCH_SIZE: int = 8
    RERANK_MAX_LENGTH: int = 1024
    RERANK_TIMEOUT_SECONDS: int = 60
    RERANK_DEVICE: str = "cpu"
    RERANK_USE_FP16: bool = False
    RERANK_ALLOW_FALLBACK: bool = True

    # Async tasks
    TASK_QUEUE_BACKEND: str = "local"  # local / redis_rq
    TASK_REDIS_URL: str = "redis://127.0.0.1:6379/0"
    TASK_QUEUE_NAME: str = "mianshiagent"
    TASK_JOB_TIMEOUT_SECONDS: int = 900
    TASK_RESULT_TTL_SECONDS: int = 86400
    TASK_FAILURE_TTL_SECONDS: int = 604800
    TASK_ALLOW_LOCAL_FALLBACK: bool = True
    TASK_MAX_RETRIES: int = 1
    TASK_PROGRESS_POLL_SECONDS: float = 1.5

    # 应用
    APP_NAME: str = "面试简历 Agent"
    APP_VERSION: str = "0.1.0"
    APP_ENV: str = "local"  # local / staging / production
    PUBLIC_BASE_URL: str = "http://127.0.0.1:5174"
    ENFORCE_RELEASE_CHECKS: bool = True
    AUTO_CREATE_DB: bool = True
    DEBUG: bool = True
    ENABLE_DOCS: bool = True
    UPLOAD_DIR: str = "uploads"
    MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10MB
    MAX_RESUME_TEXT_LENGTH: int = 80_000
    MAX_JD_TEXT_LENGTH: int = 40_000
    MAX_ANSWER_LENGTH: int = 8_000

    # 安全
    ADMIN_EMAILS: str = ""
    CORS_ALLOW_ORIGINS: list[str] = [
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://localhost:5173",
        "http://localhost:5174",
    ]
    TRUSTED_HOSTS: list[str] = ["127.0.0.1", "localhost", "testserver"]
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_AUTH_REQUESTS: int = 30
    RATE_LIMIT_API_REQUESTS: int = 180

    # 运维与发布
    METRICS_ENABLED: bool = True
    BACKUP_ENABLED: bool = False
    BACKUP_DIR: str = "backups"
    BACKUP_RETENTION_DAYS: int = 14
    DEPLOYMENT_COLOR: str = "blue"
    RELEASE_CHANNEL: str = "stable"
    CANARY_PERCENT: int = 0

    # 商业化发布开关
    BILLING_ENABLED: bool = False
    PAYMENT_PROVIDER: str = ""  # stripe / wechatpay / alipay / manual
    PAYMENT_WEBHOOK_SECRET: str = ""
    PAYMENT_CHECKOUT_BASE_URL: str = ""
    PAYMENT_SUCCESS_URL: str = ""
    PAYMENT_CANCEL_URL: str = ""
    BILLING_UPGRADE_CONTACT: str = ""
    FREE_RESUME_QUOTA: int = 1
    FREE_INTERVIEW_QUOTA: int = 1
    FREE_OPTIMIZE_QUOTA: int = 1
    FREE_JD_ADAPT_QUOTA: int = 1
    FREE_REPORT_EXPORT_QUOTA: int = 0
    PRO_MONTHLY_PRICE_CNY: int = 39
    PRO_RESUME_QUOTA: int = 10
    PRO_INTERVIEW_QUOTA: int = 20
    PRO_OPTIMIZE_QUOTA: int = 30
    PRO_JD_ADAPT_QUOTA: int = 30
    PRO_REPORT_EXPORT_QUOTA: int = 20
    SPRINT_PACKAGE_PRICE_CNY: int = 129

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() in {"prod", "production"}

    @property
    def admin_email_list(self) -> list[str]:
        return [email.strip().lower() for email in self.ADMIN_EMAILS.split(",") if email.strip()]

    @field_validator("DEBUG", "ENFORCE_RELEASE_CHECKS", "AUTO_CREATE_DB", "ENABLE_DOCS", "BILLING_ENABLED", "LLM_ALLOW_FALLBACK", "METRICS_ENABLED", "BACKUP_ENABLED", "QDRANT_SYNC_ON_STARTUP", "EMBEDDING_USE_FP16", "EMBEDDING_ALLOW_FALLBACK", "RERANK_USE_FP16", "RERANK_ALLOW_FALLBACK", "TASK_ALLOW_LOCAL_FALLBACK", mode="before")
    @classmethod
    def parse_bool_like(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production", "0", "false", "no"}:
                return False
            if normalized in {"debug", "dev", "development", "1", "true", "yes"}:
                return True
        return value

    @field_validator("CORS_ALLOW_ORIGINS", "TRUSTED_HOSTS", mode="before")
    @classmethod
    def parse_csv_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
