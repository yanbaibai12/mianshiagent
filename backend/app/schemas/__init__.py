from datetime import datetime
from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field


# ==================== Auth ====================

class UserRegisterRequest(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    password: str = Field(min_length=8, max_length=128)
    nickname: str | None = Field(default=None, max_length=100)


class UserLoginRequest(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    password: str = Field(max_length=128)


class UserResponse(BaseModel):
    id: UUID
    email: str
    nickname: str | None = None

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ==================== Organization ====================

class OrganizationCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class OrganizationMemberInviteRequest(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    role: str = Field(default="member", pattern=r"^(admin|member)$")


class OrganizationResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    plan: str
    status: str
    role: str
    created_at: datetime


class OrganizationMemberResponse(BaseModel):
    id: UUID
    user_id: UUID
    email: str
    nickname: str | None = None
    role: str
    status: str
    created_at: datetime


# ==================== Resume ====================

class ResumeCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str | None = Field(default=None, max_length=80_000)


class ResumeUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    parsed_data: dict[str, Any] | None = None
    optimized_data: dict[str, Any] | None = None


class ResumeResponse(BaseModel):
    id: UUID
    organization_id: UUID | None = None
    title: str
    original_file: str | None = None
    original_text: str | None = None
    parsed_data: dict[str, Any] | None = None
    optimized_data: dict[str, Any] | None = None
    jd_text: str | None = None
    match_score: float | None = None
    template_id: str | None = None
    is_default: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ResumeListItemResponse(BaseModel):
    id: UUID
    organization_id: UUID | None = None
    title: str
    match_score: float | None = None
    template_id: str | None = None
    is_default: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ResumeOptimizeRequest(BaseModel):
    template_id: str


class ResumeAdaptJDRequest(BaseModel):
    jd_text: str = Field(min_length=1, max_length=40_000)


class ResumeAdaptJDResponse(BaseModel):
    jd_requirements: dict[str, Any]
    match_score: float
    weak_points: list[str]
    optimized_resume: dict[str, Any]
    rag_references: list[dict[str, Any]] = Field(default_factory=list)


# ==================== Template ====================

class TemplateResponse(BaseModel):
    id: str
    name: str
    category: str | None = None
    structure: dict[str, Any]
    is_builtin: bool

    class Config:
        from_attributes = True


# ==================== Interview ====================

class InterviewCreateRequest(BaseModel):
    resume_id: UUID
    jd_text: str | None = Field(default=None, max_length=40_000)


class InterviewResponse(BaseModel):
    id: UUID
    organization_id: UUID | None = None
    resume_id: UUID | None = None
    jd_text: str | None = None
    status: str
    total_score: float | None = None
    dimension_scores: dict[str, Any] | None = None
    summary: str | None = None
    weak_points: list[str] | None = None
    suggestions: list[str] | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InterviewQuestionResponse(BaseModel):
    id: UUID
    resume_point_id: str | None = None
    point_title: str | None = None
    sequence: int
    question: str
    user_answer: str | None = None
    scores: dict[str, Any] | None = None
    total_score: float | None = None
    feedback: str | None = None
    refined_answer: str | None = None
    answered_at: datetime | None = None

    class Config:
        from_attributes = True


class AnswerSubmitRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=8_000)


class AnswerSubmitResponse(InterviewQuestionResponse):
    pass


class InterviewReportResponse(BaseModel):
    id: UUID
    total_score: float
    dimension_scores: dict[str, Any]
    summary: str
    weak_points: list[str]
    suggestions: list[str]
    questions: list[InterviewQuestionResponse]


# ==================== Knowledge / RAG ====================

class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4_000)
    categories: list[str] | None = None
    limit: int = Field(default=5, ge=1, le=10)


class KnowledgeSearchResponse(BaseModel):
    results: list[dict[str, Any]]


class KnowledgeStatsResponse(BaseModel):
    document_count: int
    chunk_count: int
    categories: list[str]


# ==================== Payment ====================

class CheckoutCreateRequest(BaseModel):
    plan: str = Field(default="pro", pattern=r"^(pro|enterprise)$")
    billing_cycle: str = Field(default="monthly", pattern=r"^(monthly|yearly|trial)$")


class CheckoutCreateResponse(BaseModel):
    order_id: UUID
    provider: str
    plan: str
    billing_cycle: str
    amount_cny: int
    status: str
    checkout_url: str | None = None
    message: str


class PaymentOrderResponse(BaseModel):
    id: UUID
    provider: str
    provider_order_id: str | None = None
    plan: str
    billing_cycle: str
    amount_cny: int
    currency: str
    status: str
    checkout_url: str | None = None
    created_at: datetime
    paid_at: datetime | None = None

    class Config:
        from_attributes = True
