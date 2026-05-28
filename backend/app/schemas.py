from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class FeatureSignal(BaseModel):
    name: str
    category: str


class ToolSignal(BaseModel):
    name: str
    category: str


class CompetitiveURLCreate(BaseModel):
    url: str = Field(min_length=3, max_length=1000)
    analysis_workspace_id: int | None = None


class CompetitiveURLRead(BaseModel):
    id: int
    url: str
    domain: str
    source_type: str
    status: str
    company_id: int | None
    company_name: str | None
    confidence: float
    http_status: int | None
    page_title: str | None
    meta_description: str | None
    headings: list[str]
    summary: str | None
    detected_features: list[FeatureSignal]
    detected_tools: list[ToolSignal]
    last_error: str | None
    published_at: datetime | None
    scraped_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CompanyNewsRead(BaseModel):
    id: int
    title: str
    article_url: str
    publisher: str | None
    summary: str | None
    published_at: datetime | None
    source: str


class CompanyClaimRead(BaseModel):
    id: int
    claim_type: str
    claim_value: str
    category: str | None
    confidence: float
    source_tier: float
    source_type: str
    source_url: str
    evidence_snippet: str | None
    source_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    last_verified_at: datetime


class EnrichmentConnectorRead(BaseModel):
    id: str
    name: str
    category: str
    method: str
    site_domain: str
    requires_api_key: bool
    enabled_by_default: bool
    target_url: str
    strategic_value: str


class DecisionPolicyRead(BaseModel):
    high_confidence_threshold: float
    claim_confidence_weights: dict[str, float]
    claim_freshness_bands: dict[str, int]
    claim_freshness_scores: dict[str, float]
    claim_corroboration: dict[str, float]
    source_tier_scores: dict[str, float]
    market_signal_sources: list[str]


class CompanySummaryRead(BaseModel):
    id: int
    company_name: str
    primary_domain: str | None
    website_url: str | None
    linkedin_url: str | None
    description: str | None
    source_count: int
    news_count: int
    linkedin_news_count: int
    enrichment_news_count: int
    high_confidence_claim_count: int
    news_source_counts: dict[str, int]
    last_refreshed_at: datetime | None
    features: list[FeatureSignal]
    tools: list[ToolSignal]


class CompanyDetailRead(CompanySummaryRead):
    sources: list[CompetitiveURLRead]
    news: list[CompanyNewsRead]
    claims: list[CompanyClaimRead]


class MergeReviewRead(BaseModel):
    id: int
    source_id: int
    source_url: str
    source_domain: str
    source_company_id: int | None
    source_company_name: str | None
    detected_company_name: str
    candidate_company_id: int
    candidate_company_name: str
    similarity_score: float
    status: str
    reason: str | None
    reviewer_note: str | None
    reviewed_at: datetime | None
    created_at: datetime


class MergeReviewAction(BaseModel):
    reviewer_note: str | None = None


class IngestionJobRead(BaseModel):
    id: int
    job_type: str
    run_mode: str
    status: str
    company_id: int | None
    company_name: str | None
    result_summary: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class CompetitorCandidateRead(BaseModel):
    company_name: str
    url: str
    segment: str
    source: str


class AutoDiscoverResponse(BaseModel):
    candidates_considered: int
    added_sources: int
    skipped_existing: int
    failed_sources: int
    urls_added: list[str]
    errors: list[str]


class AnalysisWorkspaceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=800)
    market_domain: str | None = Field(default=None, max_length=180)
    target_company_id: int | None = None
    company_ids: list[int] = Field(default_factory=list)
    competitor_company_ids: list[int] | None = None


class AnalysisWorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=800)
    market_domain: str | None = Field(default=None, max_length=180)
    target_company_id: int | None = None
    company_ids: list[int] | None = None
    competitor_company_ids: list[int] | None = None


class WorkspaceRetargetRequest(BaseModel):
    workspace_id: int | None = None
    new_target_company_id: int | None = None
    domain: str | None = Field(default=None, max_length=300)
    name: str | None = Field(default=None, min_length=2, max_length=180)
    competitor_company_ids: list[int] | None = None
    company_ids: list[int] | None = None
    force_rescrape: bool = False


class AnalysisWorkspaceRead(BaseModel):
    id: int
    name: str
    description: str | None = None
    market_domain: str | None = None
    target_company_id: int | None = None
    target_company_name: str | None = None
    default_focus_company_id: int | None = None
    default_focus_company_name: str | None = None
    company_ids: list[int]
    company_count: int
    competitor_company_ids: list[int]
    competitor_count: int
    status: str
    status_message: str | None = None
    target_version: int
    retarget_job_id: int | None = None
    recalculated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class WorkspaceRetargetResponse(BaseModel):
    workspace: AnalysisWorkspaceRead
    job_id: int
    status: str
    target_company_id: int | None = None
    target_company_name: str | None = None


class CompetitorComparisonRead(BaseModel):
    company_id: int
    company_name: str
    linkedin_url: str | None
    gap_score: float
    feature_gap_score: float
    tool_gap_score: float
    market_signal_score: float
    market_signal_count: int
    shared_feature_count: int
    shared_tool_count: int
    competitor_only_features: list[FeatureSignal]
    competitor_only_tools: list[ToolSignal]
    shared_features: list[FeatureSignal]
    shared_tools: list[ToolSignal]
    top_news: list[CompanyNewsRead]


class ComparisonRead(BaseModel):
    analysis_workspace_id: int | None = None
    analysis_workspace_name: str | None = None
    workspace_status: str | None = None
    workspace_status_message: str | None = None
    target_version: int | None = None
    focus_anchor_company_id: int | None = None
    focus_anchor_company_name: str | None = None
    baseline_company_id: int | None = None
    baseline_company_name: str
    baseline_features: list[FeatureSignal]
    baseline_tools: list[ToolSignal]
    competitors: list[CompetitorComparisonRead]


class BriefingEvidenceRead(BaseModel):
    id: int
    source_type: str
    title: str
    url: str
    publisher: str | None = None
    company_id: int
    company_name: str
    published_at: datetime | None = None
    relevance_score: float


class BriefingInsightRead(BaseModel):
    id: str
    insight_type: str
    headline: str
    summary: str
    competitor_id: int | None = None
    competitor_name: str | None = None
    impact: str
    confidence: float
    urgency: str
    recommended_action: str
    why_it_matters: str
    evidence: list[BriefingEvidenceRead]


class CoverageHealthRead(BaseModel):
    company_id: int
    company_name: str
    coverage_score: int
    status: str
    source_count: int
    news_count: int
    connector_count: int
    high_confidence_claim_count: int
    missing_sources: list[str]
    note: str


class OnboardingStepRead(BaseModel):
    id: str
    label: str
    description: str
    status: str


class BriefingRecommendationRead(BaseModel):
    id: str
    recommendation_type: str
    action: str
    urgency: str
    impact: str
    linked_insight_ids: list[str]
    owner_role: str


class BriefingRead(BaseModel):
    date: datetime
    analysis_workspace_id: int | None = None
    analysis_workspace_name: str | None = None
    workspace_status: str | None = None
    workspace_status_message: str | None = None
    target_version: int | None = None
    focus_anchor_company_id: int | None = None
    focus_anchor_company_name: str | None = None
    baseline_company_id: int | None = None
    baseline_company_name: str
    summary: str
    top_insights: list[BriefingInsightRead]
    urgent_signals: list[BriefingInsightRead]
    coverage_health: list[CoverageHealthRead]
    recommended_actions: list[BriefingRecommendationRead]
    onboarding: list[OnboardingStepRead]
    ask_suggestions: list[str]
    totals: dict[str, int]


class AskConcentricRequest(BaseModel):
    question: str = Field(min_length=3, max_length=600)
    analysis_workspace_id: int | None = None
    baseline_company_id: int | None = None
    focus_anchor_company_id: int | None = None


class AskConcentricResponse(BaseModel):
    answer: str
    why_it_matters: str
    evidence: list[BriefingEvidenceRead]
    recommended_next_step: str
    confidence: float
