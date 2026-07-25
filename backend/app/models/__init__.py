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
    token_estimate = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now)

    document = relationship("KnowledgeDocument", back_populates="chunks")


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
