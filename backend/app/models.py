from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Boolean, DateTime, Enum as SQLEnum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RoleEnum(str, Enum):
    analyst = "analyst"
    viewer = "viewer"


class CompanyTypeEnum(str, Enum):
    concentric = "concentric"
    competitor = "competitor"


class RoadmapBucketEnum(str, Enum):
    now = "now"
    next = "next"
    later = "later"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    role: Mapped[RoleEnum] = mapped_column(SQLEnum(RoleEnum), nullable=False, default=RoleEnum.viewer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    company_type: Mapped[CompanyTypeEnum] = mapped_column(SQLEnum(CompanyTypeEnum), nullable=False, index=True)
    segment: Mapped[str | None] = mapped_column(String(120), nullable=True)
    website: Mapped[str | None] = mapped_column(String(300), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    source_last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    assessments: Mapped[list[CapabilityAssessment]] = relationship(back_populates="company", cascade="all, delete-orphan")
    tool_usage: Mapped[list[ToolUsage]] = relationship(back_populates="company", cascade="all, delete-orphan")


class Feature(Base):
    __tablename__ = "features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    category: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    importance_weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    assessments: Mapped[list[CapabilityAssessment]] = relationship(back_populates="feature", cascade="all, delete-orphan")


class CapabilityAssessment(Base):
    __tablename__ = "capability_assessments"
    __table_args__ = (UniqueConstraint("company_id", "feature_id", name="uq_company_feature_assessment"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    feature_id: Mapped[int] = mapped_column(ForeignKey("features.id", ondelete="CASCADE"), nullable=False, index=True)
    concentric_coverage: Mapped[int] = mapped_column(Integer, nullable=False)
    concentric_quality: Mapped[int] = mapped_column(Integer, nullable=False)
    competitor_coverage: Mapped[int] = mapped_column(Integer, nullable=False)
    competitor_quality: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    company: Mapped[Company] = relationship(back_populates="assessments")
    feature: Mapped[Feature] = relationship(back_populates="assessments")
    evidence_items: Mapped[list[Evidence]] = relationship(back_populates="assessment", cascade="all, delete-orphan")


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("capability_assessments.id", ondelete="CASCADE"), nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    assessment: Mapped[CapabilityAssessment] = relationship(back_populates="evidence_items")


class ToolUsage(Base):
    __tablename__ = "tool_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    company: Mapped[Company] = relationship(back_populates="tool_usage")


class RoadmapItem(Base):
    __tablename__ = "roadmap_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority_bucket: Mapped[RoadmapBucketEnum] = mapped_column(SQLEnum(RoadmapBucketEnum), nullable=False, index=True)
    competitor_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True)
    feature_id: Mapped[int | None] = mapped_column(ForeignKey("features.id", ondelete="SET NULL"), nullable=True, index=True)
    owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(80), nullable=False, default="open")
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_impact: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class CompetitiveURL(Base):
    __tablename__ = "competitive_urls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    url: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True, index=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    meta_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    headings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_tools_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class CompanyProfile(Base):
    __tablename__ = "company_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_name: Mapped[str] = mapped_column(String(220), nullable=False, unique=True, index=True)
    company_key: Mapped[str] = mapped_column(String(220), nullable=False, unique=True, index=True)
    primary_domain: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    website_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    feature_set_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_set_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    news_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    sources: Mapped[list[CompanySource]] = relationship(back_populates="company", cascade="all, delete-orphan")
    news_items: Mapped[list[CompanyNews]] = relationship(back_populates="company", cascade="all, delete-orphan")
    claims: Mapped[list[CompanyClaim]] = relationship(back_populates="company", cascade="all, delete-orphan")
    merge_reviews_as_candidate: Mapped[list[CompanyMergeReview]] = relationship(
        back_populates="candidate_company",
        cascade="all, delete-orphan",
    )
    ingestion_jobs: Mapped[list[IngestionJob]] = relationship(back_populates="company", cascade="all, delete-orphan")


class CompanySource(Base):
    __tablename__ = "company_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True, index=True)
    source_domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(60), nullable=False, default="website")
    company_id: Mapped[int | None] = mapped_column(ForeignKey("company_profiles.id", ondelete="SET NULL"), nullable=True, index=True)
    detected_company_name: Mapped[str | None] = mapped_column(String(220), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    meta_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    headings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_features_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_tools_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    company: Mapped[CompanyProfile | None] = relationship(back_populates="sources")
    merge_reviews: Mapped[list[CompanyMergeReview]] = relationship(back_populates="source", cascade="all, delete-orphan")


class CompanyNews(Base):
    __tablename__ = "company_news"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(400), nullable=False)
    article_url: Mapped[str] = mapped_column(String(1200), nullable=False, unique=True, index=True)
    publisher: Mapped[str | None] = mapped_column(String(220), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="google_news_rss")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    company: Mapped[CompanyProfile] = relationship(back_populates="news_items")


class CompanyClaim(Base):
    __tablename__ = "company_claims"
    __table_args__ = (
        UniqueConstraint("company_id", "claim_type", "claim_value", name="uq_company_claim"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    claim_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    claim_value: Mapped[str] = mapped_column(String(260), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    source_tier: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False, default="website")
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    evidence_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    company: Mapped[CompanyProfile] = relationship(back_populates="claims")


class CompanyMergeReview(Base):
    __tablename__ = "company_merge_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("company_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    candidate_company_id: Mapped[int] = mapped_column(
        ForeignKey("company_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    detected_company_name: Mapped[str] = mapped_column(String(220), nullable=False)
    detected_company_key: Mapped[str] = mapped_column(String(220), nullable=False, index=True)
    candidate_company_name: Mapped[str] = mapped_column(String(220), nullable=False)
    candidate_company_key: Mapped[str] = mapped_column(String(220), nullable=False, index=True)
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending", index=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    source: Mapped[CompanySource] = relationship(back_populates="merge_reviews")
    candidate_company: Mapped[CompanyProfile] = relationship(back_populates="merge_reviews_as_candidate")


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    run_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="manual", index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="queued", index=True)
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("company_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    company: Mapped[CompanyProfile | None] = relationship(back_populates="ingestion_jobs")
