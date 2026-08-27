from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import declarative_base, relationship
import uuid

from app.utils.time import utc_now

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    nickname = Column(String(100))
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    resumes = relationship("Resume", back_populates="user", cascade="all, delete-orphan")
    interviews = relationship("Interview", back_populates="user", cascade="all, delete-orphan")
    usage_records = relationship("UsageRecord", back_populates="user", cascade="all, delete-orphan")
    billing_account = relationship("BillingAccount", back_populates="user", uselist=False, cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", foreign_keys="AuditLog.actor_user_id", back_populates="actor")
    organization_memberships = relationship("OrganizationMember", back_populates="user", cascade="all, delete-orphan")
    payment_orders = relationship("PaymentOrder", back_populates="user", cascade="all, delete-orphan")
    async_tasks = relationship("AsyncTask", back_populates="user", cascade="all, delete-orphan")
    resume_versions = relationship("ResumeVersion", back_populates="user", cascade="all, delete-orphan")
    job_applications = relationship("JobApplication", back_populates="user", cascade="all, delete-orphan")
    interview_experience_shares = relationship("InterviewExperienceShare", back_populates="user", cascade="all, delete-orphan")
    agent_question_practice_states = relationship("AgentQuestionPracticeState", back_populates="user", cascade="all, delete-orphan")
    training_profile_dimensions = relationship("TrainingProfileDimension", back_populates="user", cascade="all, delete-orphan")
    training_plans = relationship("TrainingPlan", back_populates="user", cascade="all, delete-orphan")
    quality_annotations = relationship("QualityAnnotation", back_populates="user", cascade="all, delete-orphan")
    quality_eval_candidates = relationship("QualityEvalCandidate", back_populates="user", cascade="all, delete-orphan")


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(120), nullable=False)
    slug = Column(String(140), unique=True, nullable=False)
    plan = Column(String(30), nullable=False, default="free")
    status = Column(String(30), nullable=False, default="active")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    members = relationship("OrganizationMember", back_populates="organization", cascade="all, delete-orphan")
    resumes = relationship("Resume", back_populates="organization")
    interviews = relationship("Interview", back_populates="organization")
    usage_records = relationship("UsageRecord", back_populates="organization")
    payment_orders = relationship("PaymentOrder", back_populates="organization")
    async_tasks = relationship("AsyncTask", back_populates="organization")
    resume_versions = relationship("ResumeVersion", back_populates="organization")
    job_applications = relationship("JobApplication", back_populates="organization")
    interview_experience_shares = relationship("InterviewExperienceShare", back_populates="organization")
    company_interview_profiles = relationship("CompanyInterviewProfile", back_populates="organization")
    agent_question_practice_states = relationship("AgentQuestionPracticeState", back_populates="organization")
    training_profile_dimensions = relationship("TrainingProfileDimension", back_populates="organization")
    training_plans = relationship("TrainingPlan", back_populates="organization", cascade="all, delete-orphan")
    quality_annotations = relationship("QualityAnnotation", back_populates="organization")
    quality_eval_candidates = relationship("QualityEvalCandidate", back_populates="organization")


class OrganizationMember(Base):
    __tablename__ = "organization_members"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_organization_members_org_user"),)

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(30), nullable=False, default="member")
    status = Column(String(30), nullable=False, default="active")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    organization = relationship("Organization", back_populates="members")
    user = relationship("User", back_populates="organization_memberships")


class BillingAccount(Base):
    __tablename__ = "billing_accounts"

    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    organization_id = Column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"))
    plan = Column(String(30), nullable=False, default="free")  # free / pro / enterprise
    status = Column(String(30), nullable=False, default="active")  # active / inactive / past_due
    source = Column(String(50), nullable=False, default="system")  # system / manual / payment
    expires_at = Column(DateTime)
    notes = Column(Text)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="billing_account")


class Resume(Base):
    __tablename__ = "resumes"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"))
    title = Column(String(200), nullable=False)
    original_file = Column(String(500))
    original_text = Column(Text)
    parsed_data = Column(JSON)
    optimized_data = Column(JSON)
    jd_text = Column(Text)
    match_score = Column(Numeric(5, 2))
    template_id = Column(String(50))
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="resumes")
    organization = relationship("Organization", back_populates="resumes")
    interviews = relationship("Interview", back_populates="resume")
    chunks = relationship("ResumeChunk", back_populates="resume", cascade="all, delete-orphan")
    versions = relationship("ResumeVersion", back_populates="resume", cascade="all, delete-orphan")
    job_applications = relationship("JobApplication", back_populates="resume")


class ResumeChunk(Base):
    __tablename__ = "resume_chunks"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resume_id = Column(Uuid(as_uuid=True), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"))
    section = Column(String(40), nullable=False)
    item_title = Column(String(200), nullable=False, default="")
    chunk_index = Column(Integer, nullable=False, default=1)
    content = Column(Text, nullable=False)
    keywords = Column(JSON, default=list)
    token_estimate = Column(Integer, default=0)
    source_hash = Column(String(64), nullable=False)
    embedding_status = Column(String(30), nullable=False, default="pending")
    vector_point_id = Column(String(80))
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    resume = relationship("Resume", back_populates="chunks")


class ResumeVersion(Base):
    __tablename__ = "resume_versions"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resume_id = Column(Uuid(as_uuid=True), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"))
    version_number = Column(Integer, nullable=False, default=1)
    version_type = Column(String(40), nullable=False, default="original")
    title = Column(String(200), nullable=False)
    jd_text = Column(Text)
    data = Column(JSON, nullable=False)
    ats_report = Column(JSON, default=dict)
    change_details = Column(JSON, default=list)
    source_task_id = Column(Uuid(as_uuid=True), ForeignKey("async_tasks.id", ondelete="SET NULL"))
    parent_version_id = Column(Uuid(as_uuid=True), ForeignKey("resume_versions.id", ondelete="SET NULL"))
    source_job_id = Column(Uuid(as_uuid=True), ForeignKey("job_applications.id", ondelete="SET NULL"))
    is_current = Column(Boolean, nullable=False, default=False)
    status = Column(String(30), nullable=False, default="active")
    created_by = Column(String(40), nullable=False, default="system")
    notes = Column(Text)
    created_at = Column(DateTime, default=utc_now)

    resume = relationship("Resume", back_populates="versions")
    user = relationship("User", back_populates="resume_versions")
    organization = relationship("Organization", back_populates="resume_versions")


class AsyncTask(Base):
    __tablename__ = "async_tasks"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"))
    task_type = Column(String(80), nullable=False)
    status = Column(String(30), nullable=False, default="queued")
    progress = Column(Integer, nullable=False, default=0)
    stage = Column(String(200), nullable=False, default="已排队")
    resource_type = Column(String(80))
    resource_id = Column(String(120))
    input_payload = Column(JSON, default=dict)
    result_payload = Column(JSON, default=dict)
    error_type = Column(String(120))
    error_message = Column(Text)
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=1)
    queue_backend = Column(String(40), nullable=False, default="local")
    queue_name = Column(String(80), nullable=False, default="local")
    external_job_id = Column(String(120))
    cancel_requested = Column(Boolean, nullable=False, default=False)
    enqueued_at = Column(DateTime)
    last_heartbeat_at = Column(DateTime)
    started_at = Column(DateTime)
    ended_at = Column(DateTime)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="async_tasks")
    organization = relationship("Organization", back_populates="async_tasks")


class JobApplication(Base):
    __tablename__ = "job_applications"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"))
    resume_id = Column(Uuid(as_uuid=True), ForeignKey("resumes.id", ondelete="SET NULL"))
    current_resume_version_id = Column(Uuid(as_uuid=True), ForeignKey("resume_versions.id", ondelete="SET NULL"))
    company = Column(String(160), nullable=False, default="")
    title = Column(String(200), nullable=False)
    jd_text = Column(Text, nullable=False)
    status = Column(String(40), nullable=False, default="draft")
    match_score = Column(Numeric(5, 2))
    ats_report = Column(JSON, default=dict)
    interview_id = Column(Uuid(as_uuid=True), ForeignKey("interviews.id", ondelete="SET NULL"))
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="job_applications")
    organization = relationship("Organization", back_populates="job_applications")
    resume = relationship("Resume", back_populates="job_applications")


class ResumeTemplate(Base):
    __tablename__ = "resume_templates"

    id = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False)
    category = Column(String(50))
    structure = Column(JSON, nullable=False)
    prompt = Column(Text, nullable=False)
    is_builtin = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)


class Interview(Base):
    __tablename__ = "interviews"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"))
    resume_id = Column(Uuid(as_uuid=True), ForeignKey("resumes.id", ondelete="SET NULL"))
    jd_text = Column(Text)
    status = Column(String(20), default="ongoing")
    total_score = Column(Numeric(5, 2))
    dimension_scores = Column(JSON)
    summary = Column(Text)
    weak_points = Column(JSON)
    suggestions = Column(JSON)
    report_details = Column(JSON, default=dict)
    interview_template_id = Column(String(80), nullable=False, default="comprehensive")
    interview_template_name = Column(String(120), nullable=False, default="综合面")
    template_config_snapshot = Column(JSON, default=dict)
    target_company = Column(String(160))
    target_position = Column(String(200))
    company_profile_id = Column(Uuid(as_uuid=True), ForeignKey("company_interview_profiles.id", ondelete="SET NULL"))
    company_profile_snapshot = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="interviews")
    organization = relationship("Organization", back_populates="interviews")
    resume = relationship("Resume", back_populates="interviews")
    questions = relationship("InterviewQuestion", back_populates="interview", cascade="all, delete-orphan")
    company_profile = relationship("CompanyInterviewProfile", back_populates="interviews")


class InterviewQuestion(Base):
    __tablename__ = "interview_questions"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    interview_id = Column(Uuid(as_uuid=True), ForeignKey("interviews.id", ondelete="CASCADE"), nullable=False)
    resume_point_id = Column(String(50))
    point_title = Column(String(200))
    module = Column(String(40), nullable=False, default="resume")
    source_section = Column(String(200), default="")
    question_type = Column(String(60), nullable=False, default="resume_core")
    sequence = Column(Integer, nullable=False)
    question = Column(Text, nullable=False)
    user_answer = Column(Text)
    scores = Column(JSON)
    score_details = Column(JSON, default=dict)
    total_score = Column(Numeric(5, 2))
    feedback = Column(Text)
    refined_answer = Column(Text)
    evidence = Column(JSON, default=list)
    question_quality = Column(JSON, default=dict)
    answered_at = Column(DateTime)
    created_at = Column(DateTime, default=utc_now)

    interview = relationship("Interview", back_populates="questions")


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"))
    feature = Column(String(50), nullable=False)
    units = Column(Integer, nullable=False, default=1)
    record_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=utc_now)

    user = relationship("User", back_populates="usage_records")
    organization = relationship("Organization", back_populates="usage_records")


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(200), unique=True, nullable=False)
    category = Column(String(50), nullable=False)
    source = Column(String(200), default="builtin")
    tags = Column(JSON, default=list)
    is_builtin = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    chunks = relationship("KnowledgeChunk", back_populates="document", cascade="all, delete-orphan")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(Uuid(as_uuid=True), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False)
    sequence = Column(Integer, nullable=False, default=1)
    content = Column(Text, nullable=False)
    keywords = Column(JSON, default=list)
    chunk_metadata = Column("metadata", JSON, default=dict)
    token_estimate = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now)

    document = relationship("KnowledgeDocument", back_populates="chunks")


class InterviewExperienceShare(Base):
    __tablename__ = "interview_experience_shares"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"))
    company = Column(String(160), nullable=False)
    position = Column(String(200), nullable=False)
    city = Column(String(80))
    interview_date = Column(Date)
    rounds = Column(String(200), default="")
    difficulty = Column(String(30), nullable=False, default="medium")
    result = Column(String(30), nullable=False, default="unknown")
    tags = Column(JSON, default=list)
    questions = Column(JSON, default=list)
    process = Column(Text)
    content = Column(Text, nullable=False)
    visibility = Column(String(30), nullable=False, default="public")
    is_anonymous = Column(Boolean, nullable=False, default=True)
    status = Column(String(30), nullable=False, default="published")
    allow_profile_usage = Column(Boolean, nullable=False, default=True)
    view_count = Column(Integer, nullable=False, default=0)
    like_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="interview_experience_shares")
    organization = relationship("Organization", back_populates="interview_experience_shares")


class CompanyInterviewProfile(Base):
    __tablename__ = "company_interview_profiles"
    __table_args__ = (
        UniqueConstraint(
            "scope_key",
            "normalized_company_name",
            "normalized_position_name",
            name="uq_company_profile_scope_company_position",
        ),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    scope = Column(String(30), nullable=False, default="public")
    scope_key = Column(String(80), nullable=False, default="public")
    company_name = Column(String(160), nullable=False)
    normalized_company_name = Column(String(160), nullable=False)
    position_name = Column(String(200), nullable=False)
    normalized_position_name = Column(String(200), nullable=False)
    common_rounds = Column(JSON, default=list)
    frequent_questions = Column(JSON, default=list)
    technical_topics = Column(JSON, default=list)
    difficulty_distribution = Column(JSON, default=dict)
    interview_count = Column(Integer, nullable=False, default=0)
    source_experience_ids = Column(JSON, default=list)
    first_observed_at = Column(DateTime)
    last_observed_at = Column(DateTime)
    generated_at = Column(DateTime, default=utc_now)
    profile_version = Column(Integer, nullable=False, default=1)
    profile_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    organization = relationship("Organization", back_populates="company_interview_profiles")
    interviews = relationship("Interview", back_populates="company_profile")


class AgentQuestionPracticeState(Base):
    __tablename__ = "agent_question_practice_states"
    __table_args__ = (UniqueConstraint("user_id", "question_id", name="uq_agent_question_practice_user_question"),)

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"))
    question_id = Column(String(80), nullable=False)
    mastery_status = Column(String(30), nullable=False, default="unseen")
    is_favorite = Column(Boolean, nullable=False, default=False)
    is_wrong = Column(Boolean, nullable=False, default=False)
    review_count = Column(Integer, nullable=False, default=0)
    known_count = Column(Integer, nullable=False, default=0)
    wrong_count = Column(Integer, nullable=False, default=0)
    next_review_at = Column(DateTime)
    last_practiced_at = Column(DateTime)
    practice_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="agent_question_practice_states")
    organization = relationship("Organization", back_populates="agent_question_practice_states")


class TrainingProfileDimension(Base):
    __tablename__ = "training_profile_dimensions"
    __table_args__ = (UniqueConstraint("user_id", "dimension_key", name="uq_training_profile_user_dimension"),)

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"))
    dimension_key = Column(String(60), nullable=False)
    dimension_label = Column(String(80), nullable=False)
    mastery_score = Column(Integer, nullable=False, default=60)
    exposure_count = Column(Integer, nullable=False, default=0)
    known_count = Column(Integer, nullable=False, default=0)
    weak_count = Column(Integer, nullable=False, default=0)
    low_score_count = Column(Integer, nullable=False, default=0)
    last_signal = Column(String(80))
    last_source = Column(String(80))
    last_practiced_at = Column(DateTime)
    profile_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="training_profile_dimensions")
    organization = relationship("Organization", back_populates="training_profile_dimensions")


class TrainingPlan(Base):
    __tablename__ = "training_plans"
    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", "week_start", name="uq_training_plan_user_org_week"),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    source_interview_id = Column(Uuid(as_uuid=True), ForeignKey("interviews.id", ondelete="SET NULL"))
    week_start = Column(Date, nullable=False)
    week_end = Column(Date, nullable=False)
    status = Column(String(30), nullable=False, default="active")
    plan_summary = Column(Text, nullable=False, default="")
    estimated_minutes = Column(Integer, nullable=False, default=0)
    completion_rate = Column(Integer, nullable=False, default=0)
    generation_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="training_plans")
    organization = relationship("Organization", back_populates="training_plans")
    source_interview = relationship("Interview", foreign_keys=[source_interview_id])
    tasks = relationship(
        "TrainingPlanTask",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="TrainingPlanTask.scheduled_date, TrainingPlanTask.priority.desc(), TrainingPlanTask.created_at",
    )


class TrainingPlanTask(Base):
    __tablename__ = "training_plan_tasks"
    __table_args__ = (
        UniqueConstraint("plan_id", "dedupe_key", name="uq_training_plan_task_dedupe"),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id = Column(Uuid(as_uuid=True), ForeignKey("training_plans.id", ondelete="CASCADE"), nullable=False)
    task_type = Column(String(40), nullable=False)
    title = Column(String(240), nullable=False)
    description = Column(Text, nullable=False, default="")
    scheduled_date = Column(Date, nullable=False)
    estimated_minutes = Column(Integer, nullable=False, default=15)
    priority = Column(Integer, nullable=False, default=50)
    status = Column(String(30), nullable=False, default="pending")
    related_question_id = Column(String(120))
    related_interview_id = Column(Uuid(as_uuid=True), ForeignKey("interviews.id", ondelete="SET NULL"))
    related_experience_id = Column(Uuid(as_uuid=True), ForeignKey("interview_experience_shares.id", ondelete="SET NULL"))
    related_company_profile_id = Column(Uuid(as_uuid=True), ForeignKey("company_interview_profiles.id", ondelete="SET NULL"))
    target_dimensions = Column(JSON, default=list)
    recommendation_reason = Column(Text, nullable=False, default="")
    dedupe_key = Column(String(180), nullable=False)
    task_metadata = Column("metadata", JSON, default=dict)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    plan = relationship("TrainingPlan", back_populates="tasks")


class QualityAnnotation(Base):
    __tablename__ = "quality_annotations"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"))
    target_type = Column(String(60), nullable=False)
    target_id = Column(String(120), nullable=False)
    score = Column(Integer, nullable=False)
    labels = Column(JSON, default=list)
    notes = Column(Text)
    status = Column(String(30), nullable=False, default="open")
    reviewer_role = Column(String(40), nullable=False, default="user")
    annotation_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="quality_annotations")
    organization = relationship("Organization", back_populates="quality_annotations")
    eval_candidate = relationship("QualityEvalCandidate", back_populates="annotation", uselist=False)


class QualityEvalCandidate(Base):
    __tablename__ = "quality_eval_candidates"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"))
    annotation_id = Column(Uuid(as_uuid=True), ForeignKey("quality_annotations.id", ondelete="SET NULL"), unique=True)
    target_type = Column(String(60), nullable=False)
    target_id = Column(String(120), nullable=False)
    source_score = Column(Integer, nullable=False)
    priority = Column(Integer, nullable=False, default=2)
    labels = Column(JSON, default=list)
    issue_summary = Column(Text)
    status = Column(String(30), nullable=False, default="open")
    candidate_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="quality_eval_candidates")
    organization = relationship("Organization", back_populates="quality_eval_candidates")
    annotation = relationship("QualityAnnotation", back_populates="eval_candidate")


class AlertNotification(Base):
    __tablename__ = "alert_notifications"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_key = Column(String(160), nullable=False)
    message_hash = Column(String(64), nullable=False)
    severity = Column(String(20), nullable=False)
    feature = Column(String(80), nullable=False, default="system")
    title = Column(String(200), nullable=False)
    destination = Column(String(200), nullable=False, default="webhook")
    status = Column(String(30), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    error_type = Column(String(120))
    error_message = Column(Text)
    sent_at = Column(DateTime)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    target_user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    organization_id = Column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"))
    event_type = Column(String(80), nullable=False)
    resource_type = Column(String(80), nullable=False)
    resource_id = Column(String(120))
    ip_address = Column(String(80))
    user_agent = Column(String(300))
    event_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=utc_now)

    actor = relationship("User", foreign_keys=[actor_user_id], back_populates="audit_logs")


class PaymentOrder(Base):
    __tablename__ = "payment_orders"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"))
    provider = Column(String(40), nullable=False)
    provider_order_id = Column(String(120), unique=True)
    plan = Column(String(30), nullable=False)
    billing_cycle = Column(String(30), nullable=False, default="monthly")
    amount_cny = Column(Integer, nullable=False)
    currency = Column(String(10), nullable=False, default="CNY")
    status = Column(String(30), nullable=False, default="pending")
    checkout_url = Column(String(600))
    raw_payload = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    paid_at = Column(DateTime)

    user = relationship("User", back_populates="payment_orders")
    organization = relationship("Organization", back_populates="payment_orders")

class AgentRunRecord(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_agent_runs_user_idempotency"),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_agent_runs_status",
        ),
        CheckConstraint("tokens_used >= 0 AND tool_calls >= 0", name="ck_agent_runs_usage_nonnegative"),
        CheckConstraint("attempts >= 1", name="ck_agent_runs_attempts_positive"),
        CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 128 AND length(request_fingerprint) = 64 "
            "AND length(objective) BETWEEN 1 AND 500",
            name="ck_agent_runs_request_lengths",
        ),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    request_fingerprint = Column(String(64), nullable=False)
    objective = Column(String(500), nullable=False)
    input_payload = Column("input", JSON, nullable=False, default=dict)
    current_agent_id = Column(String(80), nullable=False)
    budget = Column(JSON, nullable=False, default=dict)
    status = Column(String(30), nullable=False, default="queued")
    tokens_used = Column(Integer, nullable=False, default=0)
    tool_calls = Column(Integer, nullable=False, default=0)
    attempts = Column(Integer, nullable=False, default=1)
    cancel_requested = Column(Boolean, nullable=False, default=False)
    output_payload = Column("output", JSON, nullable=False, default=dict)
    state_payload = Column("state", JSON, nullable=False, default=dict)
    checkpoint = Column(JSON, nullable=False, default=dict)
    error = Column(Text)
    execution_owner = Column(String(120))
    lease_expires_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    steps = relationship(
        "AgentRunStepRecord",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentRunStepRecord.sequence",
    )
    trace_events = relationship(
        "AgentRunTraceRecord",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentRunTraceRecord.sequence",
    )


class AgentRunStepRecord(Base):
    __tablename__ = "agent_run_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_agent_run_steps_run_sequence"),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'cancelled')",
            name="ck_agent_run_steps_status",
        ),
        CheckConstraint("sequence >= 1", name="ck_agent_run_steps_sequence_positive"),
        CheckConstraint("tokens_used >= 0", name="ck_agent_run_steps_tokens_nonnegative"),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(Uuid(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    sequence = Column(Integer, nullable=False)
    agent_id = Column(String(80), nullable=False)
    status = Column(String(30), nullable=False)
    decision_kind = Column(String(30))
    tokens_used = Column(Integer, nullable=False, default=0)
    error = Column(String(160))
    started_at = Column(DateTime, nullable=False, default=utc_now)
    finished_at = Column(DateTime)

    run = relationship("AgentRunRecord", back_populates="steps")


class AgentRunTraceRecord(Base):
    __tablename__ = "agent_run_trace_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_agent_run_trace_run_sequence"),
        CheckConstraint("sequence >= 1", name="ck_agent_run_trace_sequence_positive"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Uuid(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    sequence = Column(Integer, nullable=False)
    event = Column(String(80), nullable=False)
    event_metadata = Column("metadata", JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    run = relationship("AgentRunRecord", back_populates="trace_events")
