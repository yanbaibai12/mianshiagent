from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


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

    model_config = ConfigDict(from_attributes=True)


class ResumeListItemResponse(BaseModel):
    id: UUID
    organization_id: UUID | None = None
    title: str
    match_score: float | None = None
    template_id: str | None = None
    is_default: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


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
    ats_report: dict[str, Any] = Field(default_factory=dict)
    resume_evidence: list[dict[str, Any]] = Field(default_factory=list)


class ResumeChunkResponse(BaseModel):
    id: UUID
    resume_id: UUID
    section: str
    item_title: str
    chunk_index: int
    content: str
    keywords: list[str] | None = None
    embedding_status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ResumeReindexResponse(BaseModel):
    status: str
    chunk_count: int
    collection: str
    vector: dict[str, Any] = Field(default_factory=dict)


class ResumeVersionResponse(BaseModel):
    id: UUID
    resume_id: UUID
    version_number: int
    version_type: str
    title: str
    jd_text: str | None = None
    data: dict[str, Any]
    ats_report: dict[str, Any] | None = None
    change_details: list[Any] | None = None
    parent_version_id: UUID | None = None
    source_task_id: UUID | None = None
    source_job_id: UUID | None = None
    is_current: bool = False
    status: str = "active"
    created_by: str = "system"
    notes: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AsyncTaskResponse(BaseModel):
    id: UUID
    task_type: str
    status: str
    progress: int
    stage: str
    resource_type: str | None = None
    resource_id: str | None = None
    result_payload: dict[str, Any] | None = None
    error_type: str | None = None
    error_message: str | None = None
    retry_count: int
    max_retries: int
    queue_backend: str = "local"
    queue_name: str = "local"
    external_job_id: str | None = None
    cancel_requested: bool = False
    enqueued_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ResumeAdaptJDTaskResponse(BaseModel):
    task: AsyncTaskResponse


# ==================== Template ====================

class TemplateResponse(BaseModel):
    id: str
    name: str
    category: str | None = None
    structure: dict[str, Any]
    is_builtin: bool

    model_config = ConfigDict(from_attributes=True)


# ==================== Interview ====================

class InterviewCreateRequest(BaseModel):
    resume_id: UUID
    jd_text: str | None = Field(default=None, max_length=40_000)
    template_id: str | None = Field(default=None, max_length=80)
    target_company: str | None = Field(default=None, max_length=160)
    target_position: str | None = Field(default=None, max_length=200)


class InterviewTemplateResponse(BaseModel):
    template_id: str
    name: str
    scenario: str
    module_ratios: dict[str, float]
    module_question_limits: dict[str, int]
    question_count: int
    module_order: list[str]
    question_focus: list[str]
    scoring_dimensions: list[dict[str, Any]]
    report_focus: list[str]
    use_training_profile: bool
    use_company_profile: bool
    next_round_suggestions: list[str] = Field(default_factory=list)


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
    report_details: dict[str, Any] | None = None
    interview_template_id: str = "comprehensive"
    interview_template_name: str = "综合面"
    template_config_snapshot: dict[str, Any] | None = None
    target_company: str | None = None
    target_position: str | None = None
    company_profile_id: UUID | None = None
    company_profile_snapshot: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InterviewQuestionResponse(BaseModel):
    id: UUID
    resume_point_id: str | None = None
    point_title: str | None = None
    module: str = "resume"
    source_section: str | None = None
    question_type: str = "resume_core"
    sequence: int
    question: str
    user_answer: str | None = None
    scores: dict[str, Any] | None = None
    score_details: dict[str, Any] | None = None
    total_score: float | None = None
    feedback: str | None = None
    refined_answer: str | None = None
    evidence: list[dict[str, Any]] | None = None
    question_quality: dict[str, Any] | None = None
    answered_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class AnswerSubmitRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=8_000)


class AnswerSubmitResponse(InterviewQuestionResponse):
    pass


class InterviewReportResponse(BaseModel):
    id: UUID
    interview_template_id: str = "comprehensive"
    interview_template_name: str = "综合面"
    template_config_snapshot: dict[str, Any] | None = None
    target_company: str | None = None
    target_position: str | None = None
    company_profile_id: UUID | None = None
    company_profile_snapshot: dict[str, Any] | None = None
    total_score: float
    dimension_scores: dict[str, Any]
    summary: str
    weak_points: list[str]
    suggestions: list[str]
    report_details: dict[str, Any] | None = None
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
    vector_store: dict[str, Any] = Field(default_factory=dict)


# ==================== Community / Question bank ====================

class AgentQuestionPracticeUpdateRequest(BaseModel):
    mastery_status: str | None = Field(default=None, pattern=r"^(unseen|known|unknown|review)$")
    is_favorite: bool | None = None
    is_wrong: bool | None = None
    next_review_at: datetime | None = None


class AgentQuestionPracticeStateResponse(BaseModel):
    question_id: str
    mastery_status: str
    is_favorite: bool
    is_wrong: bool
    review_count: int
    known_count: int
    wrong_count: int
    next_review_at: datetime | None = None
    last_practiced_at: datetime | None = None
    updated_at: datetime


class AgentQuestionBankItemResponse(BaseModel):
    id: str
    section: str
    difficulty: str
    roles: list[str]
    skills: list[str]
    question: str
    concise_answer: str
    deep_dive_answer: str | None = None
    focus: str
    scenario: str
    answer_points: list[str]
    followups: list[str]
    scoring: list[str]
    red_flags: list[str]
    keywords: list[str]
    tags: list[str] = Field(default_factory=list)
    source_title: str
    source_version: str
    practice_state: AgentQuestionPracticeStateResponse | None = None


class AgentQuestionBankListResponse(BaseModel):
    items: list[AgentQuestionBankItemResponse]
    total: int
    limit: int
    offset: int
    filters: dict[str, list[str]]


class TrainingProfileDimensionResponse(BaseModel):
    dimension_key: str
    dimension_label: str
    mastery_score: int
    exposure_count: int
    known_count: int
    weak_count: int
    low_score_count: int
    last_signal: str | None = None
    last_source: str | None = None
    last_practiced_at: datetime | None = None
    updated_at: datetime | None = None


class TrainingProfileResponse(BaseModel):
    dimensions: list[TrainingProfileDimensionResponse]
    weakest_dimensions: list[TrainingProfileDimensionResponse]
    stats: dict[str, Any] = Field(default_factory=dict)


# ==================== Training plans ====================

class TrainingPlanGenerateRequest(BaseModel):
    source_interview_id: UUID | None = None
    week_start: date | None = None


class TrainingPlanTaskUpdateRequest(BaseModel):
    status: str | None = Field(default=None, pattern=r"^(pending|completed|skipped)$")
    scheduled_date: date | None = None


class TrainingPlanTaskResponse(BaseModel):
    id: UUID
    task_type: str
    title: str
    description: str
    scheduled_date: date
    estimated_minutes: int
    priority: int
    status: str
    related_question_id: str | None = None
    related_interview_id: UUID | None = None
    related_experience_id: UUID | None = None
    related_company_profile_id: UUID | None = None
    target_dimensions: list[str] = Field(default_factory=list)
    recommendation_reason: str
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TrainingPlanResponse(BaseModel):
    id: UUID
    organization_id: UUID
    source_interview_id: UUID | None = None
    week_start: date
    week_end: date
    status: str
    plan_summary: str
    estimated_minutes: int
    completion_rate: int
    generation_metadata: dict[str, Any] = Field(default_factory=dict)
    tasks: list[TrainingPlanTaskResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InterviewExperienceCreateRequest(BaseModel):
    company: str = Field(min_length=1, max_length=160)
    position: str = Field(min_length=1, max_length=200)
    city: str | None = Field(default=None, max_length=80)
    interview_date: date | None = None
    rounds: str | None = Field(default=None, max_length=200)
    difficulty: str = Field(default="medium", pattern=r"^(easy|medium|hard|unknown)$")
    result: str = Field(default="unknown", pattern=r"^(offer|passed|failed|pending|unknown)$")
    tags: list[str] = Field(default_factory=list, max_length=12)
    questions: list[str] = Field(default_factory=list, max_length=20)
    process: str | None = Field(default=None, max_length=4_000)
    content: str = Field(min_length=10, max_length=12_000)
    visibility: str = Field(default="public", pattern=r"^(public|organization|private)$")
    is_anonymous: bool = True
    allow_profile_usage: bool = True


class InterviewExperienceUpdateRequest(BaseModel):
    company: str | None = Field(default=None, max_length=160)
    position: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=80)
    interview_date: date | None = None
    rounds: str | None = Field(default=None, max_length=200)
    difficulty: str | None = Field(default=None, pattern=r"^(easy|medium|hard|unknown)$")
    result: str | None = Field(default=None, pattern=r"^(offer|passed|failed|pending|unknown)$")
    tags: list[str] | None = Field(default=None, max_length=12)
    questions: list[str] | None = Field(default=None, max_length=20)
    process: str | None = Field(default=None, max_length=4_000)
    content: str | None = Field(default=None, min_length=10, max_length=12_000)
    visibility: str | None = Field(default=None, pattern=r"^(public|organization|private)$")
    is_anonymous: bool | None = None
    allow_profile_usage: bool | None = None


class InterviewExperienceResponse(BaseModel):
    id: UUID
    organization_id: UUID | None = None
    company: str
    position: str
    city: str | None = None
    interview_date: date | None = None
    rounds: str | None = None
    difficulty: str
    result: str
    tags: list[str] | None = None
    questions: list[str] | None = None
    process: str | None = None
    content: str
    visibility: str
    is_anonymous: bool
    allow_profile_usage: bool
    status: str
    view_count: int
    like_count: int
    author_label: str
    can_edit: bool
    created_at: datetime
    updated_at: datetime


class InterviewExperienceListResponse(BaseModel):
    items: list[InterviewExperienceResponse]
    total: int
    limit: int
    offset: int


class CompanyProfileRebuildRequest(BaseModel):
    company: str | None = Field(default=None, max_length=160)
    position: str | None = Field(default=None, max_length=200)
    scope: str | None = Field(default=None, pattern=r"^(public|organization)$")


class CompanyInterviewProfileResponse(BaseModel):
    id: UUID
    organization_id: UUID | None = None
    scope: str
    company_name: str
    normalized_company_name: str
    position_name: str
    normalized_position_name: str
    common_rounds: list[dict[str, Any]] = Field(default_factory=list)
    frequent_questions: list[dict[str, Any]] = Field(default_factory=list)
    technical_topics: list[dict[str, Any]] = Field(default_factory=list)
    difficulty_distribution: dict[str, int] = Field(default_factory=dict)
    interview_count: int
    source_experience_ids: list[UUID] | None = None
    profile_confidence: str
    first_observed_at: datetime | None = None
    last_observed_at: datetime | None = None
    generated_at: datetime | None = None
    updated_at: datetime | None = None
    profile_version: int


class CompanyInterviewProfileListResponse(BaseModel):
    items: list[CompanyInterviewProfileResponse]
    total: int
    limit: int
    offset: int


class CompanyProfileRebuildResponse(BaseModel):
    rebuilt_count: int
    profile_ids: list[UUID] = Field(default_factory=list)


# ==================== Job Workbench ====================

class JobApplicationCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    company: str | None = Field(default="", max_length=160)
    jd_text: str = Field(min_length=1, max_length=40_000)
    resume_id: UUID | None = None


class JobApplicationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    company: str | None = Field(default=None, max_length=160)
    jd_text: str | None = Field(default=None, max_length=40_000)
    resume_id: UUID | None = None
    status: str | None = Field(default=None, pattern=r"^(draft|matching|optimized|interviewing|reported|archived)$")


class JobApplicationResponse(BaseModel):
    id: UUID
    organization_id: UUID | None = None
    resume_id: UUID | None = None
    current_resume_version_id: UUID | None = None
    company: str
    title: str
    jd_text: str
    status: str
    match_score: float | None = None
    ats_report: dict[str, Any] | None = None
    interview_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
