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
    last_refreshed_at: datetime | None
    features: list[FeatureSignal]
    tools: list[ToolSignal]


class CompanyDetailRead(CompanySummaryRead):
    sources: list[CompetitiveURLRead]
    news: list[CompanyNewsRead]


class CompetitorComparisonRead(BaseModel):
    company_id: int
    company_name: str
    linkedin_url: str | None
    gap_score: float
    competitor_only_features: list[FeatureSignal]
    competitor_only_tools: list[ToolSignal]
    shared_features: list[FeatureSignal]
    shared_tools: list[ToolSignal]
    top_news: list[CompanyNewsRead]


class ComparisonRead(BaseModel):
    baseline_company_name: str
    baseline_features: list[FeatureSignal]
    baseline_tools: list[ToolSignal]
    competitors: list[CompetitorComparisonRead]
