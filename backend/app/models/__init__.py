from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON, Numeric, Boolean, Integer, Uuid, UniqueConstraint
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
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="interviews")
    organization = relationship("Organization", back_populates="interviews")
    resume = relationship("Resume", back_populates="interviews")
    questions = relationship("InterviewQuestion", back_populates="interview", cascade="all, delete-orphan")


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
    total_score = Column(Numeric(5, 2))
    feedback = Column(Text)
    refined_answer = Column(Text)
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
