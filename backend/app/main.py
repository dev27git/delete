from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy import Select, delete, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, selectinload

from .ai_enrichment import extract_ai_signals
from .database import Base, SessionLocal, engine, get_db
from .discovery import discover_competitor_candidates, discover_market_landscape_candidates, list_competitor_catalog
from .enrichment import fetch_enrichment_news, list_enrichment_connectors
from .models import (
    AnalysisWorkspace,
    AnalysisWorkspaceCompany,
    AnalysisWorkspaceSource,
    CompanyClaim,
    CompanyMergeReview,
    CompanyNews,
    CompanyProfile,
    CompanySource,
    IngestionJob,
)
from .schemas import (
    AnalysisWorkspaceCreate,
    AnalysisWorkspaceRead,
    AnalysisWorkspaceUpdate,
    AskConcentricRequest,
    AskConcentricResponse,
    AutoDiscoverResponse,
    BriefingEvidenceRead,
    BriefingInsightRead,
    BriefingRead,
    BriefingRecommendationRead,
    CoverageHealthRead,
    DecisionPolicyRead,
    CompetitorCandidateRead,
    CompanyClaimRead,
    CompanyDetailRead,
    CompanyNewsRead,
    CompanySummaryRead,
    ComparisonRead,
    CompetitiveURLCreate,
    CompetitiveURLRead,
    CompetitorComparisonRead,
    EnrichmentConnectorRead,
    FeatureSignal,
    IngestionJobRead,
    MergeReviewAction,
    MergeReviewRead,
    OnboardingStepRead,
    ToolSignal,
    WorkspaceRetargetRequest,
    WorkspaceRetargetResponse,
)
from .scraper import (
    FeatureHit,
    ToolHit,
    _dedupe_feature_hits,
    _dedupe_tool_hits,
    _domain_feature_hints,
    _domain_tool_hints,
    _extract_features,
    _extract_tools,
    derive_linkedin_company_url,
    extract_domain,
    extract_linkedin_company_url,
    fetch_company_news,
    fetch_linkedin_news,
    infer_company_name_from_domain,
    normalize_company_key,
    normalize_url,
    resolve_google_news_article_url,
    scrape_source_url,
)

BASELINE_COMPANY_NAME = "Concentric AI"
BASELINE_COMPANY_URL = "https://concentric.ai/"
SCHEDULE_INTERVAL_SECONDS = int(os.getenv("SCHEDULE_INTERVAL_SECONDS", "1800"))
SCHEDULE_ENABLED = os.getenv("SCHEDULE_ENABLED", "1").lower() not in {"0", "false", "no"}
MERGE_REVIEW_THRESHOLD = 0.83
MERGE_AUTO_APPROVE_THRESHOLD = 0.96
HIGH_CONFIDENCE_THRESHOLD = 0.8
CLAIM_CONFIDENCE_WEIGHTS: dict[str, float] = {
    "extraction": 0.45,
    "source_tier": 0.4,
    "freshness": 0.15,
}
CLAIM_FRESHNESS_BANDS_DAYS: dict[str, int] = {"hot": 30, "warm": 90}
CLAIM_FRESHNESS_SCORES: dict[str, float] = {"hot": 1.0, "warm": 0.85, "cold": 0.68, "unknown": 0.75}
CLAIM_CORROBORATION_PER_EXTRA_SOURCE = 0.04
CLAIM_CORROBORATION_CAP = 0.2
SOURCE_TIER_BY_TYPE: dict[str, float] = {
    "product": 0.95,
    "docs": 0.95,
    "website": 0.88,
    "linkedin": 0.7,
    "news": 0.58,
}
SOURCE_TIER_ENRICHMENT = 0.64
SOURCE_TIER_DEFAULT = 0.6
MIN_NEWS_RELEVANCE_SCORE = 0.6
GENERIC_NEWS_IDENTITY_TERMS: tuple[str, ...] = (
    "ai",
    "app",
    "cloud",
    "cyber",
    "data",
    "labs",
    "security",
    "software",
    "tech",
    "technologies",
)
PLACEHOLDER_COMPANY_MARKERS: tuple[str, ...] = (
    "access denied",
    "attention required",
    "bot verification",
    "captcha",
    "checking your browser",
    "cloudflare",
    "enable javascript",
    "forbidden",
    "human verification",
    "just a moment",
    "request blocked",
    "security check",
    "service unavailable",
    "too many requests",
    "unauthorized",
    "verify you are human",
)
NON_ENTITY_NAME_MARKERS: tuple[str, ...] = (
    "home",
    "redesign",
    "documentation",
    "docs",
    "privacy policy",
    "terms of service",
    "terms of use",
    "sign in",
    "log in",
)

_scheduler_stop_event = threading.Event()
_scheduler_thread: threading.Thread | None = None
_scheduler_lock = threading.Lock()
_refresh_cycle_lock = threading.Lock()
_write_lock = threading.RLock()

WORKSPACE_STATUS_READY = "ready"
WORKSPACE_STATUS_RECALCULATING = "recalculating_landscape"
WORKSPACE_STATUS_DISCOVERING = "discovering_market"
WORKSPACE_STATUS_HYDRATING = "hydrating_entities"
WORKSPACE_STATUS_EXTRACTING = "extracting_signals"
WORKSPACE_STATUS_CALCULATING = "calculating_gaps"
WORKSPACE_STATUS_FAILED = "recalculation_failed"

app = FastAPI(title="Competitive Intelligence API", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):51[0-9]{2}",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_runtime_schema()
    _start_scheduler()


@app.on_event("shutdown")
def on_shutdown() -> None:
    _stop_scheduler()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _ensure_runtime_schema() -> None:
    """Small SQLite migration shim for local databases created before workspace isolation fields."""
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as connection:
        workspace_info = connection.exec_driver_sql("PRAGMA table_info(analysis_workspaces)").fetchall()
        workspace_columns = {row[1] for row in workspace_info}
        if not workspace_columns:
            return
        migrations = {
            "description": "ALTER TABLE analysis_workspaces ADD COLUMN description TEXT",
            "market_domain": "ALTER TABLE analysis_workspaces ADD COLUMN market_domain VARCHAR(180)",
            "status": "ALTER TABLE analysis_workspaces ADD COLUMN status VARCHAR(40) NOT NULL DEFAULT 'ready'",
            "status_message": "ALTER TABLE analysis_workspaces ADD COLUMN status_message TEXT",
            "target_version": "ALTER TABLE analysis_workspaces ADD COLUMN target_version INTEGER NOT NULL DEFAULT 1",
            "retarget_job_id": "ALTER TABLE analysis_workspaces ADD COLUMN retarget_job_id INTEGER",
            "recalculated_at": "ALTER TABLE analysis_workspaces ADD COLUMN recalculated_at DATETIME",
        }
        for column, statement in migrations.items():
            if column not in workspace_columns:
                connection.exec_driver_sql(statement)
        _ensure_workspace_target_nullable(connection)

        membership_columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(analysis_workspace_companies)").fetchall()
        }
        membership_migrations = {
            "status": "ALTER TABLE analysis_workspace_companies ADD COLUMN status VARCHAR(40) NOT NULL DEFAULT 'enriched_new'",
            "discovery_rank": "ALTER TABLE analysis_workspace_companies ADD COLUMN discovery_rank INTEGER",
            "market_position": "ALTER TABLE analysis_workspace_companies ADD COLUMN market_position VARCHAR(80)",
            "feature_set_json": "ALTER TABLE analysis_workspace_companies ADD COLUMN feature_set_json TEXT",
            "tool_set_json": "ALTER TABLE analysis_workspace_companies ADD COLUMN tool_set_json TEXT",
            "source_count": "ALTER TABLE analysis_workspace_companies ADD COLUMN source_count INTEGER NOT NULL DEFAULT 0",
            "news_count": "ALTER TABLE analysis_workspace_companies ADD COLUMN news_count INTEGER NOT NULL DEFAULT 0",
            "last_hydrated_at": "ALTER TABLE analysis_workspace_companies ADD COLUMN last_hydrated_at DATETIME",
        }
        for column, statement in membership_migrations.items():
            if column not in membership_columns:
                connection.exec_driver_sql(statement)

        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS analysis_workspace_sources (
                id INTEGER NOT NULL,
                workspace_id INTEGER NOT NULL,
                source_id INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                CONSTRAINT uq_analysis_workspace_source UNIQUE (workspace_id, source_id),
                FOREIGN KEY(workspace_id) REFERENCES analysis_workspaces (id) ON DELETE CASCADE,
                FOREIGN KEY(source_id) REFERENCES company_sources (id) ON DELETE CASCADE
            )
            """
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_analysis_workspace_sources_workspace_id ON analysis_workspace_sources (workspace_id)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_analysis_workspace_sources_source_id ON analysis_workspace_sources (source_id)"
        )


def _ensure_workspace_target_nullable(connection: Any) -> None:
    target_info = next(
        (row for row in connection.exec_driver_sql("PRAGMA table_info(analysis_workspaces)").fetchall() if row[1] == "target_company_id"),
        None,
    )
    if not target_info or not target_info[3]:
        return
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS analysis_workspaces_new (
            id INTEGER NOT NULL,
            name VARCHAR(180) NOT NULL,
            description TEXT,
            market_domain VARCHAR(180),
            target_company_id INTEGER,
            status VARCHAR(40) NOT NULL DEFAULT 'ready',
            status_message TEXT,
            target_version INTEGER NOT NULL DEFAULT 1,
            retarget_job_id INTEGER,
            recalculated_at DATETIME,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            UNIQUE (name),
            FOREIGN KEY(target_company_id) REFERENCES company_profiles (id) ON DELETE CASCADE,
            FOREIGN KEY(retarget_job_id) REFERENCES ingestion_jobs (id) ON DELETE SET NULL
        )
        """
    )
    connection.exec_driver_sql(
        """
        INSERT INTO analysis_workspaces_new (
            id, name, description, market_domain, target_company_id, status, status_message,
            target_version, retarget_job_id, recalculated_at, created_at, updated_at
        )
        SELECT
            id, name, description, market_domain, target_company_id, status, status_message,
            target_version, retarget_job_id, recalculated_at, created_at, updated_at
        FROM analysis_workspaces
        """
    )
    connection.exec_driver_sql("DROP TABLE analysis_workspaces")
    connection.exec_driver_sql("ALTER TABLE analysis_workspaces_new RENAME TO analysis_workspaces")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_analysis_workspaces_id ON analysis_workspaces (id)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_analysis_workspaces_name ON analysis_workspaces (name)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_analysis_workspaces_market_domain ON analysis_workspaces (market_domain)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_analysis_workspaces_status ON analysis_workspaces (status)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_analysis_workspaces_target_company_id ON analysis_workspaces (target_company_id)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_analysis_workspaces_retarget_job_id ON analysis_workspaces (retarget_job_id)")
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")


@app.get("/enrichment-connectors", response_model=list[EnrichmentConnectorRead])
def list_connectors() -> list[EnrichmentConnectorRead]:
    return [
        EnrichmentConnectorRead(
            id=connector.id,
            name=connector.name,
            category=connector.category,
            method=connector.method,
            site_domain=connector.site_domain,
            requires_api_key=connector.requires_api_key,
            enabled_by_default=connector.enabled_by_default,
            target_url=connector.target_url,
            strategic_value=connector.strategic_value,
        )
        for connector in list_enrichment_connectors()
    ]


@app.get("/decision-policy", response_model=DecisionPolicyRead)
def get_decision_policy() -> DecisionPolicyRead:
    connectors = list_enrichment_connectors()
    market_signal_sources = ["google_news_rss", "linkedin_news_rss"]
    market_signal_sources.extend(
        [f"enrichment:{connector.id}" for connector in connectors if connector.enabled_by_default]
    )
    return DecisionPolicyRead(
        high_confidence_threshold=HIGH_CONFIDENCE_THRESHOLD,
        claim_confidence_weights=CLAIM_CONFIDENCE_WEIGHTS,
        claim_freshness_bands=CLAIM_FRESHNESS_BANDS_DAYS,
        claim_freshness_scores=CLAIM_FRESHNESS_SCORES,
        claim_corroboration={
            "per_extra_source": CLAIM_CORROBORATION_PER_EXTRA_SOURCE,
            "max_bonus": CLAIM_CORROBORATION_CAP,
        },
        source_tier_scores={
            **SOURCE_TIER_BY_TYPE,
            "enrichment": SOURCE_TIER_ENRICHMENT,
            "default": SOURCE_TIER_DEFAULT,
        },
        market_signal_sources=market_signal_sources,
    )


@app.get("/competitors/catalog", response_model=list[CompetitorCandidateRead])
def list_competitor_discovery_catalog() -> list[CompetitorCandidateRead]:
    return [
        CompetitorCandidateRead(
            company_name=item.company_name,
            url=item.url,
            segment=item.segment,
            source=item.source,
        )
        for item in list_competitor_catalog()
    ]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_domain(url: str) -> str:
    return extract_domain(normalize_url(url)).removeprefix("www.")


def _is_placeholder_company_name(company_name: str | None) -> bool:
    if not company_name:
        return True
    cleaned = company_name.strip()
    lowered = cleaned.lower()
    if not lowered:
        return True
    if any(marker in lowered for marker in PLACEHOLDER_COMPANY_MARKERS):
        return True
    if any(marker in lowered for marker in NON_ENTITY_NAME_MARKERS):
        return True
    if lowered.startswith("reference #"):
        return True
    if "|" in cleaned or ":" in cleaned:
        return True
    if len(cleaned) > 72:
        return True
    if len(cleaned.split()) > 7:
        return True
    return False


def _safe_company_name(company_name: str | None, domain: str | None) -> str:
    if not _is_placeholder_company_name(company_name):
        return (company_name or "").strip()
    if domain:
        return infer_company_name_from_domain(domain)
    return "Unknown Company"


def _dump_features(features: list[FeatureSignal]) -> str:
    return json.dumps([{"name": item.name, "category": item.category} for item in features], ensure_ascii=True)


def _dump_tools(tools: list[ToolSignal]) -> str:
    return json.dumps([{"name": item.name, "category": item.category} for item in tools], ensure_ascii=True)


def _load_features(raw: str | None) -> list[FeatureSignal]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    result: list[FeatureSignal] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        category = item.get("category")
        if isinstance(name, str) and isinstance(category, str):
            result.append(FeatureSignal(name=name, category=category))
    return result


def _load_tools(raw: str | None) -> list[ToolSignal]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    result: list[ToolSignal] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        category = item.get("category")
        if isinstance(name, str) and isinstance(category, str):
            result.append(ToolSignal(name=name, category=category))
    return result


def _load_headings(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, str)]


def _feature_hits_to_signals(items: list[FeatureHit]) -> list[FeatureSignal]:
    return [FeatureSignal(name=item.name, category=item.category) for item in items]


def _tool_hits_to_signals(items: list[ToolHit]) -> list[ToolSignal]:
    return [ToolSignal(name=item.name, category=item.category) for item in items]


def _source_signal_text(source: CompanySource) -> str:
    return " ".join(
        item
        for item in [
            source.source_url,
            source.source_domain,
            source.detected_company_name or "",
            source.page_title or "",
            source.meta_description or "",
            " ".join(_load_headings(source.headings_json)),
            source.summary or "",
        ]
        if item
    )


def _source_features(source: CompanySource) -> list[FeatureSignal]:
    stored = _load_features(source.extracted_features_json)
    fallback_hits = _dedupe_feature_hits(
        [
            *_extract_features(_source_signal_text(source)),
            *_domain_feature_hints(source.source_url),
        ]
    )
    return _merge_feature_sets(stored, _feature_hits_to_signals(fallback_hits))


def _source_tools(source: CompanySource) -> list[ToolSignal]:
    stored = _load_tools(source.extracted_tools_json)
    fallback_hits = _dedupe_tool_hits(
        [
            *_extract_tools(_source_signal_text(source)),
            *_domain_tool_hints(source.source_url),
        ]
    )
    return _merge_tool_sets(stored, _tool_hits_to_signals(fallback_hits))


def _serialize_source(source: CompanySource) -> CompetitiveURLRead:
    company_name = None
    if source.company:
        company_name = _safe_company_name(source.company.company_name, source.source_domain)
    else:
        company_name = _safe_company_name(source.detected_company_name, source.source_domain)
    return CompetitiveURLRead(
        id=source.id,
        url=source.source_url,
        domain=source.source_domain,
        source_type=source.source_type,
        status="partial" if source.last_error and source.company_id else "failed" if source.last_error else "scraped",
        company_id=source.company_id,
        company_name=company_name,
        confidence=source.confidence,
        http_status=source.http_status,
        page_title=source.page_title,
        meta_description=source.meta_description,
        headings=_load_headings(source.headings_json),
        summary=source.summary,
        detected_features=_source_features(source),
        detected_tools=_source_tools(source),
        last_error=source.last_error,
        published_at=source.published_at,
        scraped_at=source.scraped_at,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def _serialize_news(news: CompanyNews) -> CompanyNewsRead:
    return CompanyNewsRead(
        id=news.id,
        title=news.title,
        article_url=news.article_url,
        publisher=news.publisher,
        summary=news.summary,
        published_at=news.published_at,
        source=news.source,
    )


def _serialize_claim(claim: CompanyClaim) -> CompanyClaimRead:
    return CompanyClaimRead(
        id=claim.id,
        claim_type=claim.claim_type,
        claim_value=claim.claim_value,
        category=claim.category,
        confidence=claim.confidence,
        source_tier=claim.source_tier,
        source_type=claim.source_type,
        source_url=claim.source_url,
        evidence_snippet=claim.evidence_snippet,
        source_count=claim.source_count,
        first_seen_at=claim.first_seen_at,
        last_seen_at=claim.last_seen_at,
        last_verified_at=claim.last_verified_at,
    )


def _serialize_merge_review(review: CompanyMergeReview) -> MergeReviewRead:
    source_company = review.source.company if review.source else None
    source_domain = review.source.source_domain if review.source else ""
    source_company_name = _safe_company_name(source_company.company_name if source_company else None, source_domain)
    candidate_domain = review.candidate_company.primary_domain if review.candidate_company else None
    candidate_company_name = _safe_company_name(review.candidate_company_name, candidate_domain)
    detected_company_name = _safe_company_name(review.detected_company_name, source_domain)
    return MergeReviewRead(
        id=review.id,
        source_id=review.source_id,
        source_url=review.source.source_url if review.source else "",
        source_domain=source_domain,
        source_company_id=source_company.id if source_company else None,
        source_company_name=source_company_name if source_company else None,
        detected_company_name=detected_company_name,
        candidate_company_id=review.candidate_company_id,
        candidate_company_name=candidate_company_name,
        similarity_score=review.similarity_score,
        status=review.status,
        reason=review.reason,
        reviewer_note=review.reviewer_note,
        reviewed_at=review.reviewed_at,
        created_at=review.created_at,
    )


def _serialize_ingestion_job(job: IngestionJob) -> IngestionJobRead:
    return IngestionJobRead(
        id=job.id,
        job_type=job.job_type,
        run_mode=job.run_mode,
        status=job.status,
        company_id=job.company_id,
        company_name=_safe_company_name(job.company.company_name if job.company else None, job.company.primary_domain if job.company else None)
        if job.company
        else None,
        result_summary=job.result_summary,
        error_message=job.error_message,
        started_at=job.started_at,
        finished_at=job.finished_at,
        created_at=job.created_at,
    )


def _payload_field_was_set(payload: Any, field_name: str) -> bool:
    fields_set = getattr(payload, "model_fields_set", None)
    if fields_set is None:
        fields_set = getattr(payload, "__fields_set__", set())
    return field_name in fields_set


def _clean_workspace_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _workspace_company_ids(workspace: AnalysisWorkspace) -> set[int]:
    company_ids = {membership.company_id for membership in workspace.competitors}
    if workspace.target_company_id:
        company_ids.add(workspace.target_company_id)
    return company_ids


def _workspace_company_ids_from_payload(payload: Any) -> list[int]:
    if _payload_field_was_set(payload, "company_ids") and getattr(payload, "company_ids", None) is not None:
        raw_company_ids = payload.company_ids
    elif getattr(payload, "competitor_company_ids", None) is not None:
        raw_company_ids = payload.competitor_company_ids
    else:
        raw_company_ids = []
    company_ids = {int(company_id) for company_id in raw_company_ids if int(company_id) > 0}
    if getattr(payload, "target_company_id", None):
        company_ids.add(int(payload.target_company_id))
    return sorted(company_ids)


def _serialize_analysis_workspace(workspace: AnalysisWorkspace) -> AnalysisWorkspaceRead:
    company_ids = sorted(_workspace_company_ids(workspace))
    target_company_name = (
        _safe_company_name(workspace.target_company.company_name, workspace.target_company.primary_domain)
        if workspace.target_company
        else None
    )
    return AnalysisWorkspaceRead(
        id=workspace.id,
        name=workspace.name,
        description=workspace.description,
        market_domain=workspace.market_domain,
        target_company_id=workspace.target_company_id,
        target_company_name=target_company_name,
        default_focus_company_id=workspace.target_company_id,
        default_focus_company_name=target_company_name,
        company_ids=company_ids,
        company_count=len(company_ids),
        competitor_company_ids=company_ids,
        competitor_count=len(company_ids),
        status=workspace.status or WORKSPACE_STATUS_READY,
        status_message=workspace.status_message,
        target_version=workspace.target_version or 1,
        retarget_job_id=workspace.retarget_job_id,
        recalculated_at=workspace.recalculated_at,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
    )


def _load_analysis_workspace(db: Session, workspace_id: int) -> AnalysisWorkspace:
    workspace = db.scalar(
        select(AnalysisWorkspace)
        .where(AnalysisWorkspace.id == workspace_id)
        .execution_options(populate_existing=True)
        .options(
            selectinload(AnalysisWorkspace.target_company),
            selectinload(AnalysisWorkspace.competitors).selectinload(AnalysisWorkspaceCompany.company),
        )
    )
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis workspace not found")
    return workspace


def _validate_company_ids(db: Session, company_ids: set[int]) -> set[int]:
    if not company_ids:
        return set()
    existing_ids = set(db.scalars(select(CompanyProfile.id).where(CompanyProfile.id.in_(company_ids))).all())
    missing_ids = company_ids - existing_ids
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company id(s) not found: {', '.join(str(item) for item in sorted(missing_ids))}",
        )
    return existing_ids


def _set_workspace_companies(
    db: Session,
    workspace: AnalysisWorkspace,
    company_ids: list[int],
) -> None:
    normalized_company_ids = {int(company_id) for company_id in company_ids if int(company_id) > 0}
    _validate_company_ids(db, normalized_company_ids)
    existing_by_company_id = {membership.company_id: membership for membership in workspace.competitors}
    workspace.competitors[:] = [
        membership for membership in workspace.competitors if membership.company_id in normalized_company_ids
    ]
    for company_id in sorted(normalized_company_ids - set(existing_by_company_id)):
        workspace.competitors.append(AnalysisWorkspaceCompany(company_id=company_id))


def _set_workspace_competitors(
    db: Session,
    workspace: AnalysisWorkspace,
    competitor_company_ids: list[int],
) -> None:
    _set_workspace_companies(db, workspace, competitor_company_ids)


def _upsert_workspace_membership(
    db: Session,
    workspace: AnalysisWorkspace,
    company_id: int,
    *,
    discovery_rank: int | None = None,
    market_position: str | None = None,
) -> AnalysisWorkspaceCompany:
    membership = next((item for item in workspace.competitors if item.company_id == company_id), None)
    if membership is None:
        membership = AnalysisWorkspaceCompany(company_id=company_id)
        workspace.competitors.append(membership)
        db.flush()
    if discovery_rank is not None:
        membership.discovery_rank = discovery_rank
    if market_position:
        membership.market_position = market_position
    membership.status = "enriched_new"
    return membership


def _link_workspace_source(db: Session, workspace_id: int, source_id: int) -> None:
    exists = db.scalar(
        select(AnalysisWorkspaceSource).where(
            AnalysisWorkspaceSource.workspace_id == workspace_id,
            AnalysisWorkspaceSource.source_id == source_id,
        )
    )
    if not exists:
        db.add(AnalysisWorkspaceSource(workspace_id=workspace_id, source_id=source_id))


def _workspace_linked_sources(db: Session, workspace_id: int, company_id: int) -> list[CompanySource]:
    source_ids = db.scalars(
        select(AnalysisWorkspaceSource.source_id).where(AnalysisWorkspaceSource.workspace_id == workspace_id)
    ).all()
    if not source_ids:
        return []
    return db.scalars(
        select(CompanySource)
        .where(
            CompanySource.id.in_(source_ids),
            CompanySource.company_id == company_id,
        )
        .order_by(CompanySource.confidence.desc(), CompanySource.updated_at.desc())
    ).all()


def _refresh_workspace_member_snapshot(
    db: Session,
    workspace: AnalysisWorkspace,
    membership: AnalysisWorkspaceCompany,
) -> None:
    company = db.get(CompanyProfile, membership.company_id)
    if not company:
        return
    sources = _workspace_linked_sources(db=db, workspace_id=workspace.id, company_id=membership.company_id)
    if not sources:
        # Legacy/manual workspaces created before source links still need useful comparisons.
        sources = db.scalars(
            select(CompanySource)
            .where(CompanySource.company_id == membership.company_id)
            .order_by(CompanySource.confidence.desc(), CompanySource.updated_at.desc())
        ).all()

    merged_features: list[FeatureSignal] = []
    merged_tools: list[ToolSignal] = []
    for source in sources:
        merged_features = _merge_feature_sets(merged_features, _source_features(source))
        merged_tools = _merge_tool_sets(merged_tools, _source_tools(source))

    membership.feature_set_json = _dump_features(merged_features)
    membership.tool_set_json = _dump_tools(merged_tools)
    membership.source_count = len(sources)
    membership.news_count = company.news_count or 0
    membership.last_hydrated_at = _now()
    membership.status = "enriched_new" if sources else "discovered"


def _refresh_workspace_snapshots(db: Session, workspace: AnalysisWorkspace) -> None:
    for membership in list(workspace.competitors):
        _refresh_workspace_member_snapshot(db=db, workspace=workspace, membership=membership)


def _attach_source_to_workspace(
    db: Session,
    *,
    workspace: AnalysisWorkspace,
    source: CompanySource,
) -> None:
    if not source.company_id:
        return
    membership = _upsert_workspace_membership(
        db=db,
        workspace=workspace,
        company_id=source.company_id,
    )
    _link_workspace_source(db=db, workspace_id=workspace.id, source_id=source.id)
    _refresh_workspace_member_snapshot(db=db, workspace=workspace, membership=membership)
    if workspace.target_company_id is None:
        workspace.target_company_id = source.company_id
    if workspace.status != WORKSPACE_STATUS_READY:
        workspace.status = WORKSPACE_STATUS_READY
        workspace.status_message = "Discovered sources added; workspace is ready."


def _refresh_workspace_links_for_source(
    db: Session,
    *,
    source: CompanySource,
    workspace_ids: list[int] | None = None,
) -> None:
    target_workspace_ids = workspace_ids
    if target_workspace_ids is None:
        target_workspace_ids = list(
            db.scalars(
                select(AnalysisWorkspaceSource.workspace_id).where(
                    AnalysisWorkspaceSource.source_id == source.id
                )
            ).all()
        )
    for workspace_id in dict.fromkeys(target_workspace_ids):
        workspace = _load_analysis_workspace(db, workspace_id)
        _attach_source_to_workspace(db=db, workspace=workspace, source=source)


def _workspace_member_features(
    membership: AnalysisWorkspaceCompany | None,
    company: CompanyProfile,
) -> list[FeatureSignal]:
    if membership and membership.feature_set_json is not None:
        return _load_features(membership.feature_set_json)
    return _load_features(company.feature_set_json)


def _workspace_member_tools(
    membership: AnalysisWorkspaceCompany | None,
    company: CompanyProfile,
) -> list[ToolSignal]:
    if membership and membership.tool_set_json is not None:
        return _load_tools(membership.tool_set_json)
    return _load_tools(company.tool_set_json)


def _run_workspace_landscape_discovery_job(workspace_id: int, job_id: int) -> None:
    db = SessionLocal()
    try:
        with _write_lock:
            workspace = _load_analysis_workspace(db, workspace_id)
            job = db.get(IngestionJob, job_id)
            if job:
                job.status = "running"
                job.started_at = job.started_at or _now()
            market_domain = _clean_workspace_text(workspace.market_domain) or workspace.name
            workspace.status = WORKSPACE_STATUS_DISCOVERING
            workspace.status_message = f"Scoping the {market_domain} landscape..."
            db.flush()

            candidates = discover_market_landscape_candidates(
                market_domain=market_domain,
                max_count=7,
                include_news=False,
            )
            if not candidates:
                raise RuntimeError(f"No vendors discovered for market domain: {market_domain}")

            workspace.status = WORKSPACE_STATUS_HYDRATING
            workspace.status_message = "Hydrating discovered vendor entities..."
            db.flush()

            hydrated_company_ids: list[int] = []
            source_urls: list[str] = []
            for rank, candidate in enumerate(candidates, start=1):
                url = normalize_url(candidate.url)
                domain = extract_domain(url)
                if not url or not domain:
                    continue
                source = db.scalar(select(CompanySource).where(CompanySource.source_url == url))
                if source is None:
                    source = CompanySource(
                        source_url=url,
                        source_domain=domain,
                        source_type="discovered",
                        confidence=0.0,
                        scraped_at=_now(),
                        detected_company_name=candidate.company_name,
                    )
                    db.add(source)
                    db.flush()

                if source.company_id is None or source.extracted_features_json is None or source.last_error:
                    source = _scrape_and_merge_source(
                        db=db,
                        source=source,
                        refresh_market_signals=False,
                    )

                if source.company_id is None:
                    continue

                membership = _upsert_workspace_membership(
                    db=db,
                    workspace=workspace,
                    company_id=source.company_id,
                    discovery_rank=rank,
                    market_position="leader" if rank == 1 else "peer",
                )
                _link_workspace_source(db=db, workspace_id=workspace.id, source_id=source.id)
                _refresh_workspace_member_snapshot(db=db, workspace=workspace, membership=membership)
                hydrated_company_ids.append(source.company_id)
                source_urls.append(source.source_url)

            if not hydrated_company_ids:
                raise RuntimeError(f"No vendor entities could be hydrated for market domain: {market_domain}")

            workspace.status = WORKSPACE_STATUS_EXTRACTING
            workspace.status_message = "Extracting workspace-local features, tools, and source signals..."
            _refresh_workspace_snapshots(db=db, workspace=workspace)
            db.flush()

            anchor_membership = sorted(
                workspace.competitors,
                key=lambda item: (
                    item.discovery_rank if item.discovery_rank is not None else 999,
                    -item.source_count,
                    item.company_id,
                ),
            )[0]
            workspace.target_company_id = anchor_membership.company_id
            workspace.target_version = (workspace.target_version or 1) + 1

            workspace.status = WORKSPACE_STATUS_CALCULATING
            workspace.status_message = "Calculating the initial gap matrix..."
            db.flush()
            _build_comparison(
                db=db,
                analysis_workspace_id=workspace.id,
                focus_anchor_company_id=workspace.target_company_id,
                refresh_baseline=False,
                scrape_missing_baseline=False,
            )

            workspace.status = WORKSPACE_STATUS_READY
            workspace.status_message = "Autonomous landscape discovery complete."
            workspace.recalculated_at = _now()
            if job:
                job.status = "success"
                job.result_summary = json.dumps(
                    {
                        "workspace_id": workspace.id,
                        "market_domain": market_domain,
                        "companies": len(set(hydrated_company_ids)),
                        "sources": source_urls,
                        "default_focus_company_id": workspace.target_company_id,
                    },
                    ensure_ascii=True,
                )
                job.finished_at = _now()
            db.commit()
    except Exception as exc:
        db.rollback()
        with _write_lock:
            workspace = db.get(AnalysisWorkspace, workspace_id)
            if workspace:
                workspace.status = WORKSPACE_STATUS_FAILED
                workspace.status_message = str(exc)
            if job := db.get(IngestionJob, job_id):
                job.status = "failed"
                job.error_message = str(exc)
                job.finished_at = _now()
            db.commit()
    finally:
        db.close()


def _start_workspace_discovery(workspace_id: int, job_id: int) -> None:
    if os.getenv("WORKSPACE_DISCOVERY_INLINE", "0").lower() in {"1", "true", "yes"} or "PYTEST_CURRENT_TEST" in os.environ:
        _run_workspace_landscape_discovery_job(workspace_id=workspace_id, job_id=job_id)
        return
    thread = threading.Thread(
        target=_run_workspace_landscape_discovery_job,
        kwargs={"workspace_id": workspace_id, "job_id": job_id},
        daemon=True,
    )
    thread.start()


def _validate_workspace_name_available(db: Session, name: str, workspace_id: int | None = None) -> None:
    duplicate_stmt = select(AnalysisWorkspace).where(func.lower(AnalysisWorkspace.name) == name.lower())
    if workspace_id is not None:
        duplicate_stmt = duplicate_stmt.where(AnalysisWorkspace.id != workspace_id)
    if db.scalar(duplicate_stmt):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Analysis workspace name already exists")


def _resolve_retarget_target(
    db: Session,
    *,
    new_target_company_id: int | None,
    domain: str | None,
    force_rescrape: bool = False,
) -> CompanyProfile:
    if new_target_company_id is not None:
        target = db.get(CompanyProfile, new_target_company_id)
        if not target:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target company not found")
        return target

    normalized = normalize_url(domain or "")
    target_domain = extract_domain(normalized)
    if not target_domain:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide new_target_company_id or a valid domain",
        )

    target = db.scalar(select(CompanyProfile).where(CompanyProfile.primary_domain == target_domain).limit(1))
    if target:
        return target

    source = db.scalar(
        select(CompanySource)
        .where(CompanySource.source_domain == target_domain)
        .options(selectinload(CompanySource.company))
        .limit(1)
    )
    if source and source.company and not force_rescrape:
        return source.company

    if source is None:
        source = CompanySource(
            source_url=normalized,
            source_domain=target_domain,
            source_type="website",
            confidence=0.0,
            scraped_at=_now(),
        )
        db.add(source)
        db.flush()

    source = _scrape_and_merge_source(db=db, source=source, refresh_market_signals=True)
    if source.company:
        return source.company

    return _resolve_or_create_company(
        db=db,
        company_name=infer_company_name_from_domain(target_domain),
        domain=target_domain,
        source_url=normalized,
        source=source,
    )


def _resolve_workspace_for_retarget(
    db: Session,
    *,
    workspace_id: int | None,
    target: CompanyProfile,
    requested_name: str | None = None,
) -> tuple[AnalysisWorkspace, bool]:
    if workspace_id is not None:
        return _load_analysis_workspace(db, workspace_id), False

    workspaces = db.scalars(
        select(AnalysisWorkspace)
        .options(
            selectinload(AnalysisWorkspace.target_company),
            selectinload(AnalysisWorkspace.competitors).selectinload(AnalysisWorkspaceCompany.company),
        )
        .order_by(AnalysisWorkspace.updated_at.desc(), AnalysisWorkspace.name.asc())
    ).all()
    if len(workspaces) == 1:
        return workspaces[0], False
    if len(workspaces) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="workspace_id is required when multiple analysis workspaces exist",
        )

    target_name = _safe_company_name(target.company_name, target.primary_domain)
    name = (requested_name or f"{target_name} Competitive Landscape").strip()
    if len(name) < 2:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Analysis workspace name is required")
    _validate_workspace_name_available(db, name)
    workspace = AnalysisWorkspace(name=name, target_company_id=target.id)
    db.add(workspace)
    db.flush()
    all_company_ids = set(db.scalars(select(CompanyProfile.id)).all())
    _set_workspace_companies(db, workspace, sorted(all_company_ids))
    return workspace, True


def _run_workspace_retarget_pipeline(
    db: Session,
    *,
    workspace_id: int,
    target_company_id: int,
    target_version: int,
    job_id: int,
    force_rescrape: bool = False,
) -> AnalysisWorkspace:
    workspace = _load_analysis_workspace(db, workspace_id)
    job = db.get(IngestionJob, job_id)
    target = db.scalar(
        select(CompanyProfile)
        .where(CompanyProfile.id == target_company_id)
        .options(
            selectinload(CompanyProfile.sources),
            selectinload(CompanyProfile.news_items),
            selectinload(CompanyProfile.claims),
        )
    )
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target company not found")

    phase_summary: dict[str, Any] = {
        "phase_a_target_baseline": {},
        "phase_b_competitor_remap": {},
        "phase_c_gap_matrix": {},
    }
    try:
        if force_rescrape:
            for source in list(target.sources):
                _scrape_and_merge_source(db=db, source=source, refresh_market_signals=False)
            db.flush()
            target = db.get(CompanyProfile, target_company_id) or target

        news_counts = _refresh_company_news(db=db, company=target)
        enrichment_counts = _refresh_company_enrichment(db=db, company=target)
        _recompute_company_profile(db=db, company=target)
        phase_summary["phase_a_target_baseline"] = {
            "features": len(_load_features(target.feature_set_json)),
            "tools": len(_load_tools(target.tool_set_json)),
            "news": news_counts,
            "enrichment": enrichment_counts,
        }

        workspace_company_ids = _workspace_company_ids(workspace)
        competitor_ids = sorted(workspace_company_ids - {target_company_id})
        competitors = db.scalars(
            select(CompanyProfile).where(CompanyProfile.id.in_(competitor_ids))
            if competitor_ids
            else select(CompanyProfile).where(CompanyProfile.id == -1)
        ).all()
        for competitor in competitors:
            _recompute_company_profile(db=db, company=competitor)
        phase_summary["phase_b_competitor_remap"] = {"competitors": len(competitors)}

        comparison = _build_comparison(
            db=db,
            analysis_workspace_id=workspace_id,
            focus_anchor_company_id=target_company_id,
            refresh_baseline=False,
            scrape_missing_baseline=False,
        )
        phase_summary["phase_c_gap_matrix"] = {
            "rows": len(comparison.competitors),
            "max_gap_score": max((row.gap_score for row in comparison.competitors), default=0),
        }

        workspace = _load_analysis_workspace(db, workspace_id)
        workspace.status = WORKSPACE_STATUS_READY
        workspace.status_message = "Landscape recalculated successfully."
        workspace.recalculated_at = _now()
        workspace.target_version = target_version
        if job:
            job.status = "success"
            job.result_summary = json.dumps(
                {
                    "workspace_id": workspace_id,
                    "target_company_id": target_company_id,
                    "target_version": target_version,
                    **phase_summary,
                },
                ensure_ascii=True,
            )
            job.finished_at = _now()
        db.commit()
        return _load_analysis_workspace(db, workspace_id)
    except Exception as exc:
        db.rollback()
        workspace = _load_analysis_workspace(db, workspace_id)
        workspace.status = WORKSPACE_STATUS_FAILED
        workspace.status_message = str(exc)
        if job := db.get(IngestionJob, job_id):
            job.status = "failed"
            job.error_message = str(exc)
            job.finished_at = _now()
        db.commit()
        raise


def _serialize_company_summary(
    company: CompanyProfile,
    *,
    source_urls: list[str] | None = None,
    news_source_counts: dict[str, int] | None = None,
    high_confidence_claim_count: int | None = None,
) -> CompanySummaryRead:
    linkedin_url = _resolve_company_linkedin_url(company, source_urls=source_urls)
    display_company_name = _safe_company_name(company.company_name, company.primary_domain)
    resolved_news_source_counts = (
        dict(sorted(news_source_counts.items()))
        if news_source_counts is not None
        else _company_news_source_counts(company)
    )
    resolved_high_confidence_claim_count = (
        high_confidence_claim_count
        if high_confidence_claim_count is not None
        else _count_high_confidence_claims(company)
    )
    resolved_news_count = sum(resolved_news_source_counts.values())
    return CompanySummaryRead(
        id=company.id,
        company_name=display_company_name,
        primary_domain=company.primary_domain,
        website_url=company.website_url,
        linkedin_url=linkedin_url,
        description=company.description,
        source_count=company.source_count,
        news_count=resolved_news_count,
        linkedin_news_count=resolved_news_source_counts.get("linkedin_news_rss", 0),
        enrichment_news_count=sum(
            count for source, count in resolved_news_source_counts.items() if source.startswith("enrichment:")
        ),
        high_confidence_claim_count=resolved_high_confidence_claim_count,
        news_source_counts=resolved_news_source_counts,
        last_refreshed_at=company.last_refreshed_at,
        features=_load_features(company.feature_set_json),
        tools=_load_tools(company.tool_set_json),
    )


def _impact_from_score(score: float) -> str:
    if score >= 12:
        return "high"
    if score >= 5:
        return "medium"
    return "low"


def _urgency_from_impact(impact: str) -> str:
    if impact == "high":
        return "this_week"
    if impact == "medium":
        return "monitor"
    return "low_priority"


def _clamp_confidence(value: float) -> float:
    return round(min(max(value, 0.35), 0.96), 2)


def _signal_names(items: list[FeatureSignal] | list[ToolSignal], limit: int = 3) -> str:
    names = [item.name for item in items[:limit]]
    if not names:
        return "new market signals"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def _briefing_evidence_from_news(company: CompanyProfile, news: CompanyNews) -> BriefingEvidenceRead:
    return BriefingEvidenceRead(
        id=news.id,
        source_type=news.source,
        title=news.title,
        url=news.article_url,
        publisher=news.publisher,
        company_id=company.id,
        company_name=_safe_company_name(company.company_name, company.primary_domain),
        published_at=news.published_at,
        relevance_score=round(_news_item_relevance_score(company=company, item=news), 2),
    )


def _briefing_evidence_from_source(company: CompanyProfile, source: CompanySource) -> BriefingEvidenceRead:
    return BriefingEvidenceRead(
        id=source.id,
        source_type=source.source_type,
        title=source.page_title or source.detected_company_name or source.source_domain,
        url=source.source_url,
        publisher=source.source_domain,
        company_id=company.id,
        company_name=_safe_company_name(company.company_name, company.primary_domain),
        published_at=source.published_at or source.scraped_at,
        relevance_score=round(source.confidence, 2),
    )


def _recent_company_evidence(company: CompanyProfile, limit: int = 3) -> list[BriefingEvidenceRead]:
    news_items = sorted(
        _relevant_company_news_items(company),
        key=lambda item: item.published_at or item.created_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    evidence = [_briefing_evidence_from_news(company, item) for item in news_items[:limit]]
    if len(evidence) >= limit:
        return evidence

    source_items = sorted(
        company.sources,
        key=lambda item: (item.confidence, item.scraped_at or item.updated_at),
        reverse=True,
    )
    for source in source_items:
        if len(evidence) >= limit:
            break
        evidence.append(_briefing_evidence_from_source(company, source))
    return evidence


def _company_connector_count(company: CompanyProfile) -> int:
    return sum(
        count
        for source, count in _company_news_source_counts(company).items()
        if source.startswith("enrichment:")
    )


def _company_coverage_health(company: CompanyProfile) -> CoverageHealthRead:
    relevant_news_count = len(_relevant_company_news_items(company))
    connector_count = _company_connector_count(company)
    high_confidence_claim_count = _count_high_confidence_claims(company)
    source_types = {source.source_type for source in company.sources}
    missing_sources: list[str] = []
    if not source_types.intersection({"website", "product", "docs", "discovered"}):
        missing_sources.append("Primary website or product page")
    if relevant_news_count == 0:
        missing_sources.append("Relevant news")
    if connector_count == 0:
        missing_sources.append("Connector market signals")
    if not _resolve_company_linkedin_url(company):
        missing_sources.append("LinkedIn/company social signal")
    if high_confidence_claim_count == 0:
        missing_sources.append("Evidence-backed claims")

    coverage_score = min(
        100,
        18
        + min(company.source_count, 4) * 12
        + min(relevant_news_count, 8) * 3
        + min(connector_count, 4) * 5
        + min(high_confidence_claim_count, 8) * 2,
    )
    if coverage_score >= 78:
        status_label = "healthy"
        note = "Enough evidence for strategic comparison."
    elif coverage_score >= 46:
        status_label = "needs_attention"
        note = "Useful but still missing source diversity."
    else:
        status_label = "thin"
        note = "Add direct product, docs, news, or LinkedIn sources before trusting strategy calls."

    return CoverageHealthRead(
        company_id=company.id,
        company_name=_safe_company_name(company.company_name, company.primary_domain),
        coverage_score=coverage_score,
        status=status_label,
        source_count=company.source_count,
        news_count=relevant_news_count,
        connector_count=connector_count,
        high_confidence_claim_count=high_confidence_claim_count,
        missing_sources=missing_sources[:4],
        note=note,
    )


def _build_onboarding_steps(
    *,
    competitor_count: int,
    source_count: int,
    insight_count: int,
    baseline: CompanyProfile,
    coverage_health: list[CoverageHealthRead],
) -> list[OnboardingStepRead]:
    baseline_name = _safe_company_name(baseline.company_name, baseline.primary_domain)
    baseline_features = _load_features(baseline.feature_set_json)
    baseline_tools = _load_tools(baseline.tool_set_json)
    healthy_companies = [item for item in coverage_health if item.status == "healthy"]
    partial_coverage = [item for item in coverage_health if item.status != "thin"]

    def status_for(condition: bool, partial: bool = False) -> str:
        if condition:
            return "complete"
        if partial:
            return "in_progress"
        return "pending"

    return [
        OnboardingStepRead(
            id="add_competitors",
            label="Add 3 competitors",
            description="Start with the companies your product, sales, or strategy teams discuss every week.",
            status=status_for(competitor_count >= 3, competitor_count > 0),
        ),
        OnboardingStepRead(
            id="generate_briefing",
            label="Generate first briefing",
            description="The analyst layer turns sources into a short list of strategic signals and evidence.",
            status=status_for(insight_count > 0, source_count > 0),
        ),
        OnboardingStepRead(
            id="profile_baseline",
            label="Confirm analysis target",
            description=f"Add or scrape {baseline_name} product evidence so gaps are compared against the right baseline.",
            status=status_for(bool(baseline_features or baseline_tools), baseline.source_count > 0),
        ),
        OnboardingStepRead(
            id="improve_coverage",
            label="Improve signal coverage",
            description="Blend website, product, news, LinkedIn, and enrichment connectors for each priority competitor.",
            status=status_for(len(healthy_companies) >= min(competitor_count, 3), bool(partial_coverage)),
        ),
        OnboardingStepRead(
            id="review_gap",
            label="Review first strategic gap",
            description=f"Open the gap view once the briefing identifies a competitor capability {baseline_name} lacks.",
            status=status_for(insight_count > 0 and competitor_count > 0),
        ),
    ]


def _recommendations_from_insights(insights: list[BriefingInsightRead]) -> list[BriefingRecommendationRead]:
    recommendations: list[BriefingRecommendationRead] = []
    for insight in insights[:4]:
        if insight.insight_type == "market_gap":
            recommendation_type = "product"
            owner_role = "product_marketing"
        elif insight.insight_type == "market_momentum":
            recommendation_type = "positioning"
            owner_role = "competitive_intelligence"
        else:
            recommendation_type = "source_quality"
            owner_role = "revops"
        recommendations.append(
            BriefingRecommendationRead(
                id=f"rec-{insight.id}",
                recommendation_type=recommendation_type,
                action=insight.recommended_action,
                urgency=insight.urgency,
                impact=insight.impact,
                linked_insight_ids=[insight.id],
                owner_role=owner_role,
            )
        )
    return recommendations


def _dedupe_feature_hits(items: list[FeatureHit]) -> list[FeatureSignal]:
    seen: set[str] = set()
    result: list[FeatureSignal] = []
    for item in items:
        key = item.name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(FeatureSignal(name=item.name, category=item.category))
    result.sort(key=lambda row: (row.category, row.name))
    return result


def _dedupe_tool_hits(items: list[ToolHit]) -> list[ToolSignal]:
    seen: set[str] = set()
    result: list[ToolSignal] = []
    for item in items:
        key = item.name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(ToolSignal(name=item.name, category=item.category))
    result.sort(key=lambda row: (row.category, row.name))
    return result


def _apply_ai_signal_enrichment(scrape: Any) -> None:
    ai_signals = extract_ai_signals(scrape)
    if ai_signals is None:
        return

    if ai_signals.features:
        scrape.detected_features.extend(
            FeatureHit(name=item.name, category=item.category)
            for item in ai_signals.features
        )
    if ai_signals.tools:
        scrape.detected_tools.extend(
            ToolHit(name=item.name, category=item.category)
            for item in ai_signals.tools
        )
    if ai_signals.summary and not scrape.summary:
        scrape.summary = ai_signals.summary

    if ai_signals.features or ai_signals.tools:
        scrape.confidence = round(min(max(scrape.confidence, scrape.confidence + 0.05), 0.99), 2)


def _merge_feature_sets(*groups: list[FeatureSignal]) -> list[FeatureSignal]:
    merged: dict[str, FeatureSignal] = {}
    for group in groups:
        for item in group:
            merged[item.name.lower()] = item
    result = list(merged.values())
    result.sort(key=lambda row: (row.category, row.name))
    return result


def _merge_tool_sets(*groups: list[ToolSignal]) -> list[ToolSignal]:
    merged: dict[str, ToolSignal] = {}
    for group in groups:
        for item in group:
            merged[item.name.lower()] = item
    result = list(merged.values())
    result.sort(key=lambda row: (row.category, row.name))
    return result


def _count_company_news(company: CompanyProfile, source: str) -> int:
    count = 0
    for item in company.news_items:
        if item.source == source and _is_relevant_company_news(company=company, item=item):
            count += 1
    return count


def _count_company_news_prefix(company: CompanyProfile, prefix: str) -> int:
    count = 0
    for item in company.news_items:
        if item.source.startswith(prefix) and _is_relevant_company_news(company=company, item=item):
            count += 1
    return count


def _company_news_source_counts(company: CompanyProfile) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in company.news_items:
        if not _is_relevant_company_news(company=company, item=item):
            continue
        counts[item.source] = counts.get(item.source, 0) + 1
    return dict(sorted(counts.items()))


def _load_company_source_urls(db: Session, company_ids: list[int]) -> dict[int, list[str]]:
    if not company_ids:
        return {}
    rows = db.execute(
        select(CompanySource.company_id, CompanySource.source_url)
        .where(CompanySource.company_id.in_(company_ids))
        .order_by(CompanySource.updated_at.desc())
    ).all()
    source_urls: dict[int, list[str]] = {}
    for company_id, source_url in rows:
        if company_id is None:
            continue
        source_urls.setdefault(company_id, []).append(source_url)
    return source_urls


def _load_company_news_source_counts(db: Session, companies: list[CompanyProfile]) -> dict[int, dict[str, int]]:
    company_ids = [company.id for company in companies]
    if not company_ids:
        return {}
    companies_by_id = {company.id: company for company in companies}
    rows = db.execute(
        select(CompanyNews)
        .where(CompanyNews.company_id.in_(company_ids))
    ).all()
    counts_by_company: dict[int, dict[str, int]] = {}
    for (item,) in rows:
        company = companies_by_id.get(item.company_id)
        if company is None or not _is_relevant_company_news(company=company, item=item):
            continue
        counts = counts_by_company.setdefault(item.company_id, {})
        counts[item.source] = counts.get(item.source, 0) + 1
    return {company_id: dict(sorted(counts.items())) for company_id, counts in counts_by_company.items()}


def _normalize_news_match_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = re.sub(r"[^a-z0-9.]+", " ", value.lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _company_news_identity_terms(company: CompanyProfile) -> list[str]:
    terms: list[str] = []
    normalized_name = _normalize_news_match_text(company.company_name)
    if normalized_name:
        terms.append(normalized_name)
        terms.extend(
            token
            for token in normalized_name.split()
            if len(token) >= 4 and token not in GENERIC_NEWS_IDENTITY_TERMS
        )

    domain = _normalize_news_match_text((company.primary_domain or "").removeprefix("www."))
    if domain:
        terms.append(domain)
        domain_root = domain.split(".", 1)[0]
        if len(domain_root) >= 4 and domain_root not in GENERIC_NEWS_IDENTITY_TERMS:
            terms.append(domain_root)

    return list(dict.fromkeys(term for term in terms if term))


def _news_text_contains_term(text: str, term: str) -> bool:
    if not text or not term:
        return False
    if " " in term or "." in term:
        return term in text
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def _direct_article_url_text(article_url: str) -> str:
    article_domain = extract_domain(article_url)
    if article_domain in {"news.google.com", "www.news.google.com"}:
        return ""
    return _normalize_news_match_text(article_url)


def _news_item_relevance_score(company: CompanyProfile, item: Any) -> float:
    identity_terms = _company_news_identity_terms(company)
    if not identity_terms:
        return 0.0

    title_summary = _normalize_news_match_text(f"{item.title} {item.summary or ''}")
    publisher = _normalize_news_match_text(item.publisher or "")
    direct_url = _direct_article_url_text(item.article_url or "")

    if any(_news_text_contains_term(title_summary, term) for term in identity_terms):
        return 0.95
    if any(_news_text_contains_term(publisher, term) for term in identity_terms):
        return 0.75
    if any(_news_text_contains_term(direct_url, term) for term in identity_terms):
        return 0.65
    return 0.0


def _is_relevant_company_news(company: CompanyProfile, item: Any) -> bool:
    return _news_item_relevance_score(company=company, item=item) >= MIN_NEWS_RELEVANCE_SCORE


def _relevant_company_news_items(company: CompanyProfile) -> list[CompanyNews]:
    return [
        item
        for item in company.news_items
        if _is_relevant_company_news(company=company, item=item)
    ]


def _prune_irrelevant_news_items(db: Session, company: CompanyProfile) -> int:
    stale_ids = [
        item.id
        for item in list(company.news_items)
        if not _is_relevant_company_news(company=company, item=item)
    ]
    if not stale_ids:
        return 0

    result = db.execute(
        delete(CompanyNews)
        .where(
            CompanyNews.company_id == company.id,
            CompanyNews.id.in_(stale_ids),
        )
        .execution_options(synchronize_session=False)
    )
    if "news_items" in company.__dict__:
        db.expire(company, ["news_items"])
    return int(result.rowcount or 0)


def _load_high_confidence_claim_counts(db: Session, company_ids: list[int]) -> dict[int, int]:
    if not company_ids:
        return {}
    rows = db.execute(
        select(CompanyClaim.company_id, func.count(CompanyClaim.id))
        .where(
            CompanyClaim.company_id.in_(company_ids),
            CompanyClaim.confidence >= HIGH_CONFIDENCE_THRESHOLD,
        )
        .group_by(CompanyClaim.company_id)
    ).all()
    return {company_id: int(count) for company_id, count in rows}


def _count_high_confidence_claims(company: CompanyProfile) -> int:
    count = 0
    for claim in company.claims:
        if claim.confidence >= HIGH_CONFIDENCE_THRESHOLD:
            count += 1
    return count


def _source_tier_score(source_type: str, source_url: str) -> float:
    if source_type in SOURCE_TIER_BY_TYPE:
        return SOURCE_TIER_BY_TYPE[source_type]
    if "enrichment:" in source_url:
        return SOURCE_TIER_ENRICHMENT
    return SOURCE_TIER_DEFAULT


def _claim_confidence(
    source_confidence: float,
    source_tier: float,
    source_count: int,
    source_timestamp: datetime | None,
) -> float:
    now = _now()
    if source_timestamp is None:
        freshness = CLAIM_FRESHNESS_SCORES["unknown"]
    else:
        if source_timestamp.tzinfo is None:
            source_timestamp = source_timestamp.replace(tzinfo=timezone.utc)
        age_days = max((now - source_timestamp).total_seconds() / 86400.0, 0.0)
        if age_days <= CLAIM_FRESHNESS_BANDS_DAYS["hot"]:
            freshness = CLAIM_FRESHNESS_SCORES["hot"]
        elif age_days <= CLAIM_FRESHNESS_BANDS_DAYS["warm"]:
            freshness = CLAIM_FRESHNESS_SCORES["warm"]
        else:
            freshness = CLAIM_FRESHNESS_SCORES["cold"]
    corroboration = min(CLAIM_CORROBORATION_CAP, CLAIM_CORROBORATION_PER_EXTRA_SOURCE * max(source_count - 1, 0))
    weighted = (
        (CLAIM_CONFIDENCE_WEIGHTS["extraction"] * source_confidence)
        + (CLAIM_CONFIDENCE_WEIGHTS["source_tier"] * source_tier)
        + (CLAIM_CONFIDENCE_WEIGHTS["freshness"] * freshness)
        + corroboration
    )
    return round(min(weighted, 0.99), 2)


def _claim_evidence_snippet(source: CompanySource) -> str | None:
    if source.summary:
        return source.summary[:360]
    if source.meta_description:
        return source.meta_description[:360]
    headings = _load_headings(source.headings_json)
    if headings:
        return " | ".join(headings[:3])[:360]
    return None


def _upsert_company_claim(
    db: Session,
    company: CompanyProfile,
    source: CompanySource,
    claim_type: str,
    claim_value: str,
    category: str | None = None,
) -> CompanyClaim:
    existing = db.scalar(
        select(CompanyClaim).where(
            CompanyClaim.company_id == company.id,
            CompanyClaim.claim_type == claim_type,
            CompanyClaim.claim_value == claim_value,
        )
    )

    tier = _source_tier_score(source_type=source.source_type, source_url=source.source_url)
    reference_time = source.published_at or source.scraped_at or _now()
    evidence = _claim_evidence_snippet(source)
    now = _now()

    if existing:
        is_new_source = source.source_url != existing.source_url
        if is_new_source:
            existing.source_count += 1
        existing.source_url = source.source_url
        existing.source_type = source.source_type
        existing.source_tier = max(existing.source_tier, tier)
        if category and not existing.category:
            existing.category = category
        if evidence and (existing.evidence_snippet is None or tier >= existing.source_tier):
            existing.evidence_snippet = evidence
        existing.last_seen_at = now
        existing.last_verified_at = now
        existing.confidence = _claim_confidence(
            source_confidence=source.confidence,
            source_tier=existing.source_tier,
            source_count=existing.source_count,
            source_timestamp=reference_time,
        )
        return existing

    claim = CompanyClaim(
        company_id=company.id,
        claim_type=claim_type,
        claim_value=claim_value,
        category=category,
        confidence=_claim_confidence(
            source_confidence=source.confidence,
            source_tier=tier,
            source_count=1,
            source_timestamp=reference_time,
        ),
        source_tier=tier,
        source_type=source.source_type,
        source_url=source.source_url,
        evidence_snippet=evidence,
        source_count=1,
        first_seen_at=now,
        last_seen_at=now,
        last_verified_at=now,
    )
    db.add(claim)
    return claim


def _refresh_claims_from_source(db: Session, company: CompanyProfile, source: CompanySource) -> None:
    features = _source_features(source)
    tools = _source_tools(source)
    for feature in features:
        _upsert_company_claim(
            db=db,
            company=company,
            source=source,
            claim_type="feature",
            claim_value=feature.name,
            category=feature.category,
        )
    for tool in tools:
        _upsert_company_claim(
            db=db,
            company=company,
            source=source,
            claim_type="tool",
            claim_value=tool.name,
            category=tool.category,
        )


def _maybe_create_merge_review(
    db: Session,
    source: CompanySource | None,
    detected_company_name: str,
    detected_company_key: str,
    candidate: CompanyProfile,
    score: float,
) -> None:
    if source is None:
        return
    existing_pending = db.scalar(
        select(CompanyMergeReview).where(
            CompanyMergeReview.source_id == source.id,
            CompanyMergeReview.candidate_company_id == candidate.id,
            CompanyMergeReview.status == "pending",
        )
    )
    if existing_pending:
        return

    review = CompanyMergeReview(
        source_id=source.id,
        candidate_company_id=candidate.id,
        detected_company_name=detected_company_name,
        detected_company_key=detected_company_key,
        candidate_company_name=candidate.company_name,
        candidate_company_key=candidate.company_key,
        similarity_score=round(score, 3),
        reason="Potential duplicate company identity detected by fuzzy key similarity.",
        status="pending",
    )
    db.add(review)


def _run_company_refresh_job(
    db: Session,
    company: CompanyProfile,
    run_mode: str,
    refresh_news: bool = True,
    refresh_enrichment: bool = True,
) -> IngestionJob:
    job = IngestionJob(
        job_type="company_refresh",
        run_mode=run_mode,
        status="running",
        company_id=company.id,
        started_at=_now(),
    )
    db.add(job)

    try:
        news_counts: dict[str, int] = {}
        enrichment_counts: dict[str, int] = {}
        if refresh_news:
            news_counts = _refresh_company_news(db=db, company=company)
        if refresh_enrichment:
            enrichment_counts = _refresh_company_enrichment(db=db, company=company)
        _recompute_company_profile(db=db, company=company)
        job.status = "success"
        job.result_summary = json.dumps(
            {"news": news_counts, "enrichment": enrichment_counts},
            ensure_ascii=True,
        )
    except Exception as exc:
        job.status = "failed"
        job.error_message = str(exc)
    finally:
        job.finished_at = _now()
        db.flush()
    return job


def _run_full_refresh_cycle(run_mode: str = "scheduled") -> int:
    if not _refresh_cycle_lock.acquire(blocking=False):
        return 0

    refreshed = 0
    try:
        with SessionLocal() as db:
            companies = db.scalars(
                select(CompanyProfile).options(
                    selectinload(CompanyProfile.sources),
                    selectinload(CompanyProfile.news_items),
                    selectinload(CompanyProfile.claims),
                )
            ).all()
            for company in companies:
                with _write_lock:
                    _run_company_refresh_job(db=db, company=company, run_mode=run_mode)
                    db.commit()
                refreshed += 1
    finally:
        _refresh_cycle_lock.release()
    return refreshed


def _scheduler_loop() -> None:
    while not _scheduler_stop_event.is_set():
        wait_completed = _scheduler_stop_event.wait(timeout=SCHEDULE_INTERVAL_SECONDS)
        if wait_completed:
            return
        _run_full_refresh_cycle(run_mode="scheduled")


def _start_scheduler() -> None:
    if not SCHEDULE_ENABLED:
        return
    global _scheduler_thread
    with _scheduler_lock:
        if _scheduler_thread and _scheduler_thread.is_alive():
            return
        _scheduler_stop_event.clear()
        _scheduler_thread = threading.Thread(
            target=_scheduler_loop,
            name="competitive-ingestion-scheduler",
            daemon=True,
        )
        _scheduler_thread.start()


def _stop_scheduler() -> None:
    global _scheduler_thread
    with _scheduler_lock:
        if not _scheduler_thread:
            return
        _scheduler_stop_event.set()
        _scheduler_thread.join(timeout=5)
        _scheduler_thread = None


def _resolve_company_linkedin_url(company: CompanyProfile, source_urls: list[str] | None = None) -> str | None:
    urls = source_urls if source_urls is not None else [source.source_url for source in company.sources]
    for source_url in urls:
        explicit = extract_linkedin_company_url(source_url)
        if explicit:
            return explicit
    lookup_name = _safe_company_name(company.company_name, company.primary_domain)
    return derive_linkedin_company_url(lookup_name)


def _resolve_or_create_company(
    db: Session,
    company_name: str,
    domain: str,
    source_url: str,
    source: CompanySource | None = None,
) -> CompanyProfile:
    company_name = _safe_company_name(company_name, domain or extract_domain(source_url))
    company_key = normalize_company_key(company_name) or normalize_company_key(domain)
    if not company_key:
        company_key = normalize_company_key(source_url)

    company = db.scalar(select(CompanyProfile).where(CompanyProfile.company_key == company_key))
    if company:
        return company

    # Prefer exact domain match before fuzzy name matching.
    domain_company = db.scalar(
        select(CompanyProfile).where(CompanyProfile.primary_domain == domain).limit(1)
    )
    if domain_company:
        return domain_company

    # Fuzzy duplicate detection: if the key is close to an existing company key,
    # route it for review unless confidence is near-certain.
    candidates = db.scalars(select(CompanyProfile)).all()
    best_candidate: CompanyProfile | None = None
    best_score = 0.0
    for candidate in candidates:
        if not candidate.company_key:
            continue
        score = SequenceMatcher(None, company_key, candidate.company_key).ratio()
        if score > best_score:
            best_candidate = candidate
            best_score = score
    if best_candidate and best_score >= MERGE_AUTO_APPROVE_THRESHOLD:
        return best_candidate

    company = CompanyProfile(
        company_name=company_name,
        company_key=company_key,
        primary_domain=domain or None,
        website_url=source_url,
        source_count=0,
        news_count=0,
        last_refreshed_at=_now(),
    )
    db.add(company)
    db.flush()

    if best_candidate and best_score >= MERGE_REVIEW_THRESHOLD:
        _maybe_create_merge_review(
            db=db,
            source=source,
            detected_company_name=company_name,
            detected_company_key=company_key,
            candidate=best_candidate,
            score=best_score,
        )

    return company


def _recompute_company_profile(db: Session, company: CompanyProfile) -> None:
    sources = db.scalars(
        select(CompanySource).where(CompanySource.company_id == company.id).order_by(CompanySource.confidence.desc())
    ).all()
    company.source_count = len(sources)
    company.last_refreshed_at = _now()

    if not sources:
        company.feature_set_json = _dump_features([])
        company.tool_set_json = _dump_tools([])
        company.description = None
        company.primary_domain = company.primary_domain or None
        company.website_url = company.website_url or None
        return

    merged_features: list[FeatureSignal] = []
    merged_tools: list[ToolSignal] = []

    def source_rank(source: CompanySource) -> tuple[int, float]:
        if source.source_type in {"product", "website", "docs"}:
            return (3, source.confidence)
        if source.source_type == "linkedin":
            return (2, source.confidence)
        return (1, source.confidence)

    best_source = sorted(sources, key=source_rank, reverse=True)[0]

    if _is_placeholder_company_name(company.company_name):
        repaired_name = _safe_company_name(best_source.detected_company_name, best_source.source_domain)
        if repaired_name and repaired_name != company.company_name:
            same_name = db.scalar(
                select(CompanyProfile).where(
                    CompanyProfile.id != company.id,
                    CompanyProfile.company_name == repaired_name,
                )
            )
            if not same_name:
                company.company_name = repaired_name
                repaired_key = normalize_company_key(repaired_name)
                if repaired_key:
                    same_key = db.scalar(
                        select(CompanyProfile).where(
                            CompanyProfile.id != company.id,
                            CompanyProfile.company_key == repaired_key,
                        )
                    )
                    if not same_key:
                        company.company_key = repaired_key

    for source in sources:
        merged_features = _merge_feature_sets(merged_features, _source_features(source))
        merged_tools = _merge_tool_sets(merged_tools, _source_tools(source))

    company.feature_set_json = _dump_features(merged_features)
    company.tool_set_json = _dump_tools(merged_tools)
    company.description = best_source.summary or best_source.meta_description or company.description
    if "linkedin.com" not in best_source.source_domain:
        company.primary_domain = best_source.source_domain or company.primary_domain
        company.website_url = best_source.source_url or company.website_url


def _add_news_items(db: Session, company: CompanyProfile, items: list[Any], source: str) -> int:
    added = 0
    for item in items:
        original_article_url = item.article_url.strip()
        if not original_article_url:
            continue
        article_url = resolve_google_news_article_url(original_article_url) or original_article_url
        if article_url != original_article_url:
            item.article_url = article_url
        if not _is_relevant_company_news(company=company, item=item):
            continue
        exists = db.scalar(select(CompanyNews).where(CompanyNews.article_url == article_url))
        if exists:
            continue
        if article_url != original_article_url:
            existing_google_row = db.scalar(
                select(CompanyNews).where(CompanyNews.article_url == original_article_url)
            )
            if existing_google_row:
                existing_google_row.article_url = article_url
                continue
        db.add(
            CompanyNews(
                company_id=company.id,
                title=item.title[:400],
                article_url=article_url,
                publisher=item.publisher,
                summary=item.summary,
                published_at=item.published_at,
                source=source,
            )
        )
        added += 1
    return added


def _update_company_news_count(db: Session, company: CompanyProfile) -> None:
    _prune_irrelevant_news_items(db=db, company=company)
    db.flush()
    company.news_count = db.scalar(select(func.count(CompanyNews.id)).where(CompanyNews.company_id == company.id)) or 0
    company.last_refreshed_at = _now()


def _refresh_company_news(db: Session, company: CompanyProfile) -> dict[str, int]:
    linkedin_url = _resolve_company_linkedin_url(company)
    lookup_name = _safe_company_name(company.company_name, company.primary_domain)
    added_counts: dict[str, int] = {}

    try:
        news_items = fetch_company_news(company_name=lookup_name, domain=company.primary_domain)
        added_counts["google_news_rss"] = _add_news_items(
            db=db,
            company=company,
            items=news_items,
            source="google_news_rss",
        )
    except Exception:
        added_counts["google_news_rss"] = 0

    try:
        linkedin_news = fetch_linkedin_news(company_name=lookup_name, linkedin_url=linkedin_url)
        added_counts["linkedin_news_rss"] = _add_news_items(
            db=db,
            company=company,
            items=linkedin_news,
            source="linkedin_news_rss",
        )
    except Exception:
        added_counts["linkedin_news_rss"] = 0

    _update_company_news_count(db=db, company=company)
    return added_counts


def _refresh_company_enrichment(db: Session, company: CompanyProfile) -> dict[str, int]:
    lookup_name = _safe_company_name(company.company_name, company.primary_domain)
    added_counts: dict[str, int] = {}
    try:
        connector_results = fetch_enrichment_news(company_name=lookup_name, domain=company.primary_domain)
    except Exception:
        connector_results = {}

    for connector_id, items in connector_results.items():
        source = f"enrichment:{connector_id}"
        added_counts[connector_id] = _add_news_items(db=db, company=company, items=items, source=source)

    _update_company_news_count(db=db, company=company)
    return added_counts


def _ensure_baseline_profile(db: Session, *, scrape_missing_source: bool = True) -> CompanyProfile:
    key = normalize_company_key(BASELINE_COMPANY_NAME)
    baseline = db.scalar(select(CompanyProfile).where(CompanyProfile.company_key == key))
    if baseline:
        return baseline

    baseline = CompanyProfile(
        company_name=BASELINE_COMPANY_NAME,
        company_key=key,
        primary_domain=extract_domain(BASELINE_COMPANY_URL),
        website_url=BASELINE_COMPANY_URL,
        source_count=0,
        news_count=0,
        last_refreshed_at=_now(),
        feature_set_json=_dump_features([]),
        tool_set_json=_dump_tools([]),
    )
    db.add(baseline)
    db.flush()

    existing_source = db.scalar(select(CompanySource).where(CompanySource.source_url == BASELINE_COMPANY_URL))
    if not existing_source:
        source = CompanySource(
            source_url=BASELINE_COMPANY_URL,
            source_domain=extract_domain(BASELINE_COMPANY_URL),
            source_type="website",
            company_id=baseline.id,
            detected_company_name=BASELINE_COMPANY_NAME,
            confidence=0.5,
            scraped_at=_now(),
        )
        db.add(source)
        db.flush()
        if scrape_missing_source:
            _scrape_and_merge_source(db=db, source=source)
    return baseline


def _scrape_and_merge_source(
    db: Session,
    source: CompanySource,
    refresh_market_signals: bool = True,
) -> CompanySource:
    source.scraped_at = _now()
    source.last_error = None
    try:
        scrape = scrape_source_url(source.source_url)
    except Exception as exc:
        source.last_error = str(exc)
        source.confidence = 0.2
        source.http_status = None
        source.page_title = None
        source.meta_description = None
        source.summary = None
        source.extracted_features_json = _dump_features([])
        source.extracted_tools_json = _dump_tools([])
        source.headings_json = json.dumps([], ensure_ascii=True)
        fallback_company_name = infer_company_name_from_domain(source.source_domain)
        source.detected_company_name = fallback_company_name
        company = _resolve_or_create_company(
            db=db,
            company_name=fallback_company_name,
            domain=source.source_domain,
            source_url=source.source_url,
            source=source,
        )
        source.company_id = company.id
        db.flush()
        _recompute_company_profile(db, company)
        if refresh_market_signals:
            _refresh_company_news(db, company)
            _refresh_company_enrichment(db, company)
        return source

    _apply_ai_signal_enrichment(scrape)

    final_url = normalize_url(scrape.final_url) or source.source_url
    duplicate = db.scalar(
        select(CompanySource).where(
            CompanySource.source_url == final_url,
            CompanySource.id != source.id,
        )
    )

    active_source = source
    if duplicate:
        # Redirected URLs may collapse to an already tracked canonical source.
        # Reuse the existing row and remove the temporary duplicate record.
        active_source = duplicate
        db.delete(source)
        db.flush()

    active_source.source_url = final_url
    active_source.source_domain = extract_domain(final_url)
    active_source.source_type = scrape.source_type
    active_source.detected_company_name = scrape.company_name
    active_source.http_status = scrape.http_status
    active_source.page_title = scrape.page_title
    active_source.meta_description = scrape.meta_description
    active_source.summary = scrape.summary
    active_source.published_at = scrape.published_at
    active_source.headings_json = json.dumps(scrape.headings, ensure_ascii=True)
    active_source.extracted_features_json = _dump_features(_dedupe_feature_hits(scrape.detected_features))
    active_source.extracted_tools_json = _dump_tools(_dedupe_tool_hits(scrape.detected_tools))
    active_source.confidence = scrape.confidence

    company = _resolve_or_create_company(
        db=db,
        company_name=scrape.company_name,
        domain=active_source.source_domain,
        source_url=final_url,
        source=active_source,
    )
    active_source.company_id = company.id
    db.flush()
    _refresh_claims_from_source(db=db, company=company, source=active_source)

    _recompute_company_profile(db, company)
    if refresh_market_signals:
        _refresh_company_news(db, company)
        _refresh_company_enrichment(db, company)
    return active_source


@app.get("/competitive-urls", response_model=list[CompetitiveURLRead])
def list_competitive_urls(
    analysis_workspace_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[CompetitiveURLRead]:
    stmt: Select[Any] = (
        select(CompanySource)
        .options(selectinload(CompanySource.company))
        .order_by(CompanySource.updated_at.desc())
    )
    if analysis_workspace_id is not None:
        _load_analysis_workspace(db, analysis_workspace_id)
        source_ids = db.scalars(
            select(AnalysisWorkspaceSource.source_id).where(
                AnalysisWorkspaceSource.workspace_id == analysis_workspace_id
            )
        ).all()
        if not source_ids:
            return []
        stmt = stmt.where(CompanySource.id.in_(source_ids))
    sources = db.scalars(stmt).all()
    return [_serialize_source(source) for source in sources]


@app.post("/competitive-urls", response_model=CompetitiveURLRead, status_code=status.HTTP_201_CREATED)
def add_competitive_url(payload: CompetitiveURLCreate, db: Session = Depends(get_db)) -> CompetitiveURLRead:
    with _write_lock:
        normalized = normalize_url(payload.url)
        if not normalized:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="URL is required")
        domain = extract_domain(normalized)
        if not domain:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid URL")
        workspace = _load_analysis_workspace(db, payload.analysis_workspace_id) if payload.analysis_workspace_id else None

        existing = db.scalar(select(CompanySource).where(CompanySource.source_url == normalized))
        if existing:
            if not workspace:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="URL already exists")
            source = existing
        else:
            source = CompanySource(
                source_url=normalized,
                source_domain=domain,
                source_type="website",
                confidence=0.0,
                scraped_at=_now(),
            )
            db.add(source)
            db.flush()

        source = _scrape_and_merge_source(db=db, source=source)
        if workspace and source.company_id:
            _attach_source_to_workspace(db=db, workspace=workspace, source=source)
        db.commit()
        db.refresh(source)
        return _serialize_source(source)


@app.post("/competitors/auto-discover", response_model=AutoDiscoverResponse)
def auto_discover_competitors(
    max_candidates: int = Query(default=30, ge=5, le=200),
    include_news: bool = Query(default=True),
    refresh_market_signals: bool = Query(default=False),
    analysis_workspace_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> AutoDiscoverResponse:
    with _write_lock:
        workspace = _load_analysis_workspace(db, analysis_workspace_id) if analysis_workspace_id else None
        if workspace and workspace.market_domain:
            candidates = discover_market_landscape_candidates(
                market_domain=workspace.market_domain,
                max_count=max_candidates,
                include_news=include_news,
            )
        else:
            candidates = discover_competitor_candidates(max_count=max_candidates, include_news=include_news)
        existing_sources = db.scalars(select(CompanySource)).all()
        existing_sources_by_domain = {
            _canonical_domain(source.source_url): source
            for source in existing_sources
        }
        existing_domains = set(existing_sources_by_domain)

        added_sources = 0
        skipped_existing = 0
        failed_sources = 0
        urls_added: list[str] = []
        errors: list[str] = []

        for candidate in candidates:
            url = normalize_url(candidate.url)
            if not url:
                skipped_existing += 1
                continue
            domain = _canonical_domain(url)
            if domain == _canonical_domain(BASELINE_COMPANY_URL):
                skipped_existing += 1
                continue
            if domain in existing_domains:
                existing_source = existing_sources_by_domain[domain]
                if workspace:
                    _attach_source_to_workspace(db=db, workspace=workspace, source=existing_source)
                    urls_added.append(existing_source.source_url)
                    added_sources += 1
                else:
                    skipped_existing += 1
                continue

            source = CompanySource(
                source_url=url,
                source_domain=domain,
                source_type="discovered",
                confidence=0.0,
                scraped_at=_now(),
                detected_company_name=candidate.company_name,
            )
            db.add(source)
            db.commit()
            db.refresh(source)

            created_source_id = source.id
            source = _scrape_and_merge_source(
                db=db,
                source=source,
                refresh_market_signals=refresh_market_signals,
            )
            existing_domains.add(domain)
            existing_domains.add(_canonical_domain(source.source_url))
            existing_sources_by_domain[domain] = source
            existing_sources_by_domain[_canonical_domain(source.source_url)] = source
            if source.id != created_source_id:
                if workspace:
                    _attach_source_to_workspace(db=db, workspace=workspace, source=source)
                    urls_added.append(source.source_url)
                    added_sources += 1
                else:
                    skipped_existing += 1
                db.commit()
                continue

            if workspace:
                _attach_source_to_workspace(db=db, workspace=workspace, source=source)
            urls_added.append(source.source_url)
            if source.last_error and source.company_id is None:
                failed_sources += 1
                errors.append(f"{source.source_url}: {source.last_error}")
            else:
                added_sources += 1
            db.commit()

        return AutoDiscoverResponse(
            candidates_considered=len(candidates),
            added_sources=added_sources,
            skipped_existing=skipped_existing,
            failed_sources=failed_sources,
            urls_added=urls_added,
            errors=errors[:50],
        )


@app.post("/competitive-urls/{source_id}/rescrape", response_model=CompetitiveURLRead)
def rescrape_competitive_url(source_id: int, db: Session = Depends(get_db)) -> CompetitiveURLRead:
    with _write_lock:
        source = db.get(CompanySource, source_id)
        if not source:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="URL not found")

        linked_workspace_ids = list(
            db.scalars(
                select(AnalysisWorkspaceSource.workspace_id).where(
                    AnalysisWorkspaceSource.source_id == source_id
                )
            ).all()
        )
        source = _scrape_and_merge_source(db=db, source=source, refresh_market_signals=False)
        _refresh_workspace_links_for_source(
            db=db,
            source=source,
            workspace_ids=linked_workspace_ids,
        )

        db.commit()
        db.refresh(source)
        return _serialize_source(source)


@app.delete("/competitive-urls/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_competitive_url(source_id: int, db: Session = Depends(get_db)) -> Response:
    with _write_lock:
        source = db.get(CompanySource, source_id)
        if not source:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="URL not found")

        company_id = source.company_id
        db.delete(source)
        db.flush()

        if company_id:
            company = db.get(CompanyProfile, company_id)
            if company:
                _recompute_company_profile(db, company)
                if company.source_count == 0 and company.company_key != normalize_company_key(BASELINE_COMPANY_NAME):
                    db.delete(company)

        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/companies", response_model=list[CompanySummaryRead])
def list_companies(db: Session = Depends(get_db)) -> list[CompanySummaryRead]:
    companies = db.scalars(
        select(CompanyProfile)
        .order_by(CompanyProfile.source_count.desc(), CompanyProfile.company_name.asc())
    ).all()
    company_ids = [company.id for company in companies]
    source_urls_by_company = _load_company_source_urls(db, company_ids)
    news_counts_by_company = _load_company_news_source_counts(db, companies)
    high_confidence_counts_by_company = _load_high_confidence_claim_counts(db, company_ids)
    return [
        _serialize_company_summary(
            company,
            source_urls=source_urls_by_company.get(company.id, []),
            news_source_counts=news_counts_by_company.get(company.id, {}),
            high_confidence_claim_count=high_confidence_counts_by_company.get(company.id, 0),
        )
        for company in companies
    ]


@app.get("/analysis-workspaces", response_model=list[AnalysisWorkspaceRead])
def list_analysis_workspaces(db: Session = Depends(get_db)) -> list[AnalysisWorkspaceRead]:
    workspaces = db.scalars(
        select(AnalysisWorkspace)
        .options(
            selectinload(AnalysisWorkspace.target_company),
            selectinload(AnalysisWorkspace.competitors).selectinload(AnalysisWorkspaceCompany.company),
        )
        .order_by(AnalysisWorkspace.updated_at.desc(), AnalysisWorkspace.name.asc())
    ).all()
    return [_serialize_analysis_workspace(workspace) for workspace in workspaces]


@app.post("/analysis-workspaces", response_model=AnalysisWorkspaceRead, status_code=status.HTTP_201_CREATED)
def create_analysis_workspace(
    payload: AnalysisWorkspaceCreate,
    db: Session = Depends(get_db),
) -> AnalysisWorkspaceRead:
    discovery_job: tuple[int, int] | None = None
    with _write_lock:
        name = payload.name.strip()
        if len(name) < 2:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Analysis workspace name is required")
        _validate_workspace_name_available(db, name)
        company_ids = _workspace_company_ids_from_payload(payload)
        market_domain = _clean_workspace_text(payload.market_domain)
        if not company_ids:
            if not market_domain:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Market Domain / Sector is required for autonomous workspace discovery",
                )
            workspace = AnalysisWorkspace(
                name=name,
                description=_clean_workspace_text(payload.description),
                market_domain=market_domain,
                target_company_id=None,
                status=WORKSPACE_STATUS_DISCOVERING,
                status_message="Autonomous Analyst Spinning Up...",
            )
            db.add(workspace)
            db.flush()
            job = IngestionJob(
                job_type="workspace_landscape_discovery",
                run_mode="autonomous",
                status="running",
                started_at=_now(),
                result_summary=json.dumps({"workspace_id": workspace.id, "market_domain": market_domain}, ensure_ascii=True),
            )
            db.add(job)
            db.flush()
            workspace.retarget_job_id = job.id
            discovery_job = (workspace.id, job.id)
            db.commit()
            response = _serialize_analysis_workspace(_load_analysis_workspace(db, workspace.id))
        else:
            _validate_company_ids(db, set(company_ids))
            default_focus_company_id = payload.target_company_id or company_ids[0]
            workspace = AnalysisWorkspace(
                name=name,
                description=_clean_workspace_text(payload.description),
                market_domain=market_domain,
                target_company_id=default_focus_company_id,
            )
            db.add(workspace)
            db.flush()
            _set_workspace_companies(db, workspace, company_ids)
            _refresh_workspace_snapshots(db=db, workspace=workspace)
            db.commit()
            response = _serialize_analysis_workspace(_load_analysis_workspace(db, workspace.id))
    if discovery_job:
        _start_workspace_discovery(workspace_id=discovery_job[0], job_id=discovery_job[1])
        with _write_lock:
            refreshed = _load_analysis_workspace(db, discovery_job[0])
            return _serialize_analysis_workspace(refreshed)
    return response


@app.put("/analysis-workspaces/{workspace_id}", response_model=AnalysisWorkspaceRead)
def update_analysis_workspace(
    workspace_id: int,
    payload: AnalysisWorkspaceUpdate,
    db: Session = Depends(get_db),
) -> AnalysisWorkspaceRead:
    with _write_lock:
        workspace = _load_analysis_workspace(db, workspace_id)
        if payload.name is not None:
            name = payload.name.strip()
            if len(name) < 2:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Analysis workspace name is required")
            _validate_workspace_name_available(db, name, workspace_id=workspace.id)
            workspace.name = name
        if _payload_field_was_set(payload, "description"):
            workspace.description = _clean_workspace_text(payload.description)
        if _payload_field_was_set(payload, "market_domain"):
            workspace.market_domain = _clean_workspace_text(payload.market_domain)
        company_ids: list[int] | None = None
        if _payload_field_was_set(payload, "company_ids") or payload.competitor_company_ids is not None:
            company_ids = _workspace_company_ids_from_payload(payload)
            if not company_ids:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Select at least one tracked company for this workspace",
                )
            _validate_company_ids(db, set(company_ids))
        if payload.target_company_id is not None:
            _validate_company_ids(db, {payload.target_company_id})
            if payload.target_company_id != workspace.target_company_id:
                workspace.target_version = (workspace.target_version or 1) + 1
                workspace.recalculated_at = None
            workspace.target_company_id = payload.target_company_id
        if company_ids is not None:
            if workspace.target_company_id not in set(company_ids):
                workspace.target_company_id = company_ids[0]
            _set_workspace_companies(db, workspace, company_ids)
        elif payload.target_company_id is not None:
            current_company_ids = sorted(_workspace_company_ids(workspace) | {payload.target_company_id})
            _set_workspace_companies(db, workspace, current_company_ids)
        db.commit()
        return _serialize_analysis_workspace(_load_analysis_workspace(db, workspace.id))


@app.delete("/analysis-workspaces/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_analysis_workspace(workspace_id: int, db: Session = Depends(get_db)) -> Response:
    with _write_lock:
        workspace = _load_analysis_workspace(db, workspace_id)
        db.delete(workspace)
        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)


def _retarget_workspace(
    payload: WorkspaceRetargetRequest,
    db: Session,
) -> WorkspaceRetargetResponse:
    job_id: int
    target_id: int
    target_version: int
    with _write_lock:
        if payload.new_target_company_id is None and not (payload.domain or "").strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provide new_target_company_id or domain",
            )
        target = _resolve_retarget_target(
            db,
            new_target_company_id=payload.new_target_company_id,
            domain=payload.domain,
            force_rescrape=payload.force_rescrape,
        )
        workspace, created = _resolve_workspace_for_retarget(
            db,
            workspace_id=payload.workspace_id,
            target=target,
            requested_name=payload.name,
        )
        if workspace.status == WORKSPACE_STATUS_RECALCULATING:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workspace is already recalculating")
        if payload.name is not None:
            name = payload.name.strip()
            if len(name) < 2:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Analysis workspace name is required")
            _validate_workspace_name_available(db, name, workspace_id=workspace.id)
            workspace.name = name

        target_id = target.id
        existing_company_ids = sorted(_workspace_company_ids(workspace))
        if payload.company_ids is not None:
            workspace_company_ids = sorted({int(company_id) for company_id in payload.company_ids if int(company_id) > 0})
        elif payload.competitor_company_ids is not None:
            workspace_company_ids = sorted({int(company_id) for company_id in payload.competitor_company_ids if int(company_id) > 0})
        else:
            workspace_company_ids = existing_company_ids
        if created and payload.company_ids is None and payload.competitor_company_ids is None:
            all_company_ids = set(db.scalars(select(CompanyProfile.id)).all())
            workspace_company_ids = sorted(all_company_ids)
        workspace_company_ids = sorted(set(workspace_company_ids) | {target_id})

        workspace.target_company_id = target_id
        workspace.target_company = target
        workspace.target_version = (workspace.target_version or 1) + 1
        target_version = workspace.target_version
        workspace.status = WORKSPACE_STATUS_RECALCULATING
        workspace.status_message = "Recalculating Landscape..."
        workspace.recalculated_at = None
        _set_workspace_companies(db, workspace, workspace_company_ids)

        job = IngestionJob(
            job_type="workspace_retarget",
            run_mode="manual",
            status="running",
            company_id=target_id,
            started_at=_now(),
        )
        db.add(job)
        db.flush()
        workspace.retarget_job_id = job.id
        job_id = job.id
        db.commit()

    try:
        with _write_lock:
            final_workspace = _run_workspace_retarget_pipeline(
                db=db,
                workspace_id=workspace.id,
                target_company_id=target_id,
                target_version=target_version,
                job_id=job_id,
                force_rescrape=payload.force_rescrape,
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    return WorkspaceRetargetResponse(
        workspace=_serialize_analysis_workspace(final_workspace),
        job_id=job_id,
        status=final_workspace.status,
        target_company_id=final_workspace.target_company_id,
        target_company_name=_safe_company_name(
            final_workspace.target_company.company_name if final_workspace.target_company else None,
            final_workspace.target_company.primary_domain if final_workspace.target_company else None,
        ),
    )


@app.post("/api/v1/workspace/re-target", response_model=WorkspaceRetargetResponse)
def retarget_active_workspace(
    payload: WorkspaceRetargetRequest,
    db: Session = Depends(get_db),
) -> WorkspaceRetargetResponse:
    return _retarget_workspace(payload=payload, db=db)


@app.post("/analysis-workspaces/{workspace_id}/re-target", response_model=WorkspaceRetargetResponse)
def retarget_analysis_workspace(
    workspace_id: int,
    payload: WorkspaceRetargetRequest,
    db: Session = Depends(get_db),
) -> WorkspaceRetargetResponse:
    payload.workspace_id = workspace_id
    return _retarget_workspace(payload=payload, db=db)


@app.get("/companies/{company_id}", response_model=CompanyDetailRead)
def get_company_detail(company_id: int, db: Session = Depends(get_db)) -> CompanyDetailRead:
    company = db.scalar(
        select(CompanyProfile)
        .where(CompanyProfile.id == company_id)
        .options(
            selectinload(CompanyProfile.sources),
            selectinload(CompanyProfile.news_items),
            selectinload(CompanyProfile.claims),
        )
    )
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    sources = sorted(company.sources, key=lambda item: item.updated_at, reverse=True)
    news_items = sorted(
        _relevant_company_news_items(company),
        key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    summary = _serialize_company_summary(company)
    return CompanyDetailRead(
        **summary.model_dump(),
        sources=[_serialize_source(source) for source in sources],
        news=[_serialize_news(item) for item in news_items[:25]],
        claims=[_serialize_claim(item) for item in sorted(company.claims, key=lambda claim: claim.confidence, reverse=True)],
    )


@app.get("/companies/{company_id}/claims", response_model=list[CompanyClaimRead])
def list_company_claims(company_id: int, db: Session = Depends(get_db)) -> list[CompanyClaimRead]:
    company = db.scalar(
        select(CompanyProfile)
        .where(CompanyProfile.id == company_id)
        .options(selectinload(CompanyProfile.claims))
    )
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    claims = sorted(company.claims, key=lambda item: (item.confidence, item.source_count), reverse=True)
    return [_serialize_claim(item) for item in claims]


@app.post("/companies/{company_id}/refresh-news", response_model=CompanyDetailRead)
def refresh_company_news(company_id: int, db: Session = Depends(get_db)) -> CompanyDetailRead:
    with _write_lock:
        company = db.get(CompanyProfile, company_id)
        if not company:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

        _run_company_refresh_job(db=db, company=company, run_mode="manual", refresh_news=True, refresh_enrichment=False)
        db.commit()
        return get_company_detail(company_id=company.id, db=db)


@app.post("/companies/{company_id}/refresh-enrichment", response_model=CompanyDetailRead)
def refresh_company_enrichment(company_id: int, db: Session = Depends(get_db)) -> CompanyDetailRead:
    with _write_lock:
        company = db.get(CompanyProfile, company_id)
        if not company:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

        _run_company_refresh_job(db=db, company=company, run_mode="manual", refresh_news=False, refresh_enrichment=True)
        db.commit()
        return get_company_detail(company_id=company.id, db=db)


@app.get("/merge-reviews", response_model=list[MergeReviewRead])
def list_merge_reviews(
    status_filter: str | None = Query(default="pending", alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[MergeReviewRead]:
    stmt = (
        select(CompanyMergeReview)
        .options(
            selectinload(CompanyMergeReview.source).selectinload(CompanySource.company),
            selectinload(CompanyMergeReview.candidate_company),
        )
        .order_by(CompanyMergeReview.created_at.desc())
        .limit(limit)
    )
    if status_filter:
        stmt = stmt.where(CompanyMergeReview.status == status_filter)
    reviews = db.scalars(stmt).all()
    return [_serialize_merge_review(review) for review in reviews]


@app.post("/merge-reviews/{review_id}/approve", response_model=MergeReviewRead)
def approve_merge_review(review_id: int, payload: MergeReviewAction, db: Session = Depends(get_db)) -> MergeReviewRead:
    with _write_lock:
        review = db.scalar(
            select(CompanyMergeReview)
            .where(CompanyMergeReview.id == review_id)
            .options(
                selectinload(CompanyMergeReview.source).selectinload(CompanySource.company),
                selectinload(CompanyMergeReview.candidate_company),
            )
        )
        if not review:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merge review not found")
        if review.status != "pending":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Merge review already resolved")

        source = review.source
        candidate = review.candidate_company
        previous_company_id = source.company_id

        source.company_id = candidate.id
        source.detected_company_name = candidate.company_name
        source.last_error = None
        _refresh_claims_from_source(db=db, company=candidate, source=source)
        _run_company_refresh_job(db=db, company=candidate, run_mode="manual")

        if previous_company_id and previous_company_id != candidate.id:
            previous_company = db.get(CompanyProfile, previous_company_id)
            if previous_company:
                _recompute_company_profile(db=db, company=previous_company)
                if previous_company.source_count == 0 and previous_company.company_key != normalize_company_key(BASELINE_COMPANY_NAME):
                    db.delete(previous_company)

        review.status = "approved"
        review.reviewer_note = payload.reviewer_note
        review.reviewed_at = _now()
        db.commit()
        db.refresh(review)
        return _serialize_merge_review(review)


@app.post("/merge-reviews/{review_id}/reject", response_model=MergeReviewRead)
def reject_merge_review(review_id: int, payload: MergeReviewAction, db: Session = Depends(get_db)) -> MergeReviewRead:
    with _write_lock:
        review = db.scalar(select(CompanyMergeReview).where(CompanyMergeReview.id == review_id))
        if not review:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merge review not found")
        if review.status != "pending":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Merge review already resolved")

        review.status = "rejected"
        review.reviewer_note = payload.reviewer_note
        review.reviewed_at = _now()
        db.commit()
        db.refresh(review)
        return _serialize_merge_review(review)


@app.get("/news/{news_id}/resolve")
def resolve_news_article(news_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    news = db.get(CompanyNews, news_id)
    if not news:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News article not found")

    article_url = news.article_url
    if extract_domain(article_url) in {"news.google.com", "www.news.google.com"}:
        with httpx.Client(timeout=2.5, follow_redirects=True) as client:
            decoded_url = resolve_google_news_article_url(article_url, client=client)
        if decoded_url:
            with _write_lock:
                duplicate = db.scalar(
                    select(CompanyNews).where(
                        CompanyNews.article_url == decoded_url,
                        CompanyNews.id != news.id,
                    )
                )
                if duplicate:
                    db.delete(news)
                else:
                    news.article_url = decoded_url
                db.commit()
            article_url = decoded_url

    return RedirectResponse(url=article_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@app.get("/ingestion-jobs", response_model=list[IngestionJobRead])
def list_ingestion_jobs(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[IngestionJobRead]:
    jobs = db.scalars(
        select(IngestionJob)
        .options(selectinload(IngestionJob.company))
        .order_by(IngestionJob.created_at.desc())
        .limit(limit)
    ).all()
    return [_serialize_ingestion_job(job) for job in jobs]


@app.post("/ingestion-jobs/run-cycle")
def run_ingestion_cycle(db: Session = Depends(get_db)) -> dict[str, int]:
    # `db` is kept to share transaction lifecycle conventions with other endpoints.
    _ = db
    refreshed = _run_full_refresh_cycle(run_mode="manual")
    return {"refreshed_companies": refreshed}


def _build_comparison(
    db: Session,
    *,
    analysis_workspace_id: int | None = None,
    baseline_company_id: int | None = None,
    focus_anchor_company_id: int | None = None,
    refresh_baseline: bool = False,
    scrape_missing_baseline: bool = True,
) -> ComparisonRead:
    workspace: AnalysisWorkspace | None = None
    competitor_scope_ids: set[int] | None = None
    if analysis_workspace_id is not None:
        workspace = _load_analysis_workspace(db, analysis_workspace_id)
        workspace_company_ids = _workspace_company_ids(workspace)
        selected_focus_anchor_id = focus_anchor_company_id or baseline_company_id or workspace.target_company_id
        if not workspace_company_ids or selected_focus_anchor_id is None:
            label = workspace.market_domain or workspace.name
            return ComparisonRead(
                analysis_workspace_id=workspace.id,
                analysis_workspace_name=workspace.name,
                workspace_status=workspace.status,
                workspace_status_message=workspace.status_message,
                target_version=workspace.target_version,
                focus_anchor_company_id=None,
                focus_anchor_company_name=None,
                baseline_company_id=None,
                baseline_company_name=label,
                baseline_features=[],
                baseline_tools=[],
                competitors=[],
            )
        if selected_focus_anchor_id not in workspace_company_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Focus anchor must be one of the workspace tracked companies",
            )
        baseline = db.get(CompanyProfile, selected_focus_anchor_id)
        if not baseline:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis target company not found")
        competitor_scope_ids = workspace_company_ids - {baseline.id}
    elif focus_anchor_company_id is not None or baseline_company_id is not None:
        selected_focus_anchor_id = focus_anchor_company_id or baseline_company_id
        baseline = db.get(CompanyProfile, selected_focus_anchor_id)
        if not baseline:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis target company not found")
    else:
        baseline = _ensure_baseline_profile(db, scrape_missing_source=scrape_missing_baseline)

    if refresh_baseline:
        try:
            with _write_lock:
                _recompute_company_profile(db, baseline)
                _refresh_company_news(db, baseline)
                db.commit()
        except OperationalError:
            # Keep comparison available even when concurrent write traffic temporarily locks SQLite.
            db.rollback()
            baseline = db.get(CompanyProfile, baseline.id) or baseline

    workspace_memberships = {membership.company_id: membership for membership in workspace.competitors} if workspace else {}
    baseline_membership = workspace_memberships.get(baseline.id) if workspace else None
    baseline_features = _workspace_member_features(baseline_membership, baseline)
    baseline_tools = _workspace_member_tools(baseline_membership, baseline)
    baseline_feature_map = {item.name.lower(): item for item in baseline_features}
    baseline_tool_map = {item.name.lower(): item for item in baseline_tools}

    competitor_stmt = (
        select(CompanyProfile)
        .where(CompanyProfile.id != baseline.id)
        .options(
            selectinload(CompanyProfile.sources),
            selectinload(CompanyProfile.news_items),
            selectinload(CompanyProfile.claims),
        )
        .order_by(CompanyProfile.source_count.desc())
    )
    if competitor_scope_ids is not None:
        if not competitor_scope_ids:
            competitors = []
        else:
            competitors = db.scalars(competitor_stmt.where(CompanyProfile.id.in_(competitor_scope_ids))).all()
    else:
        competitors = db.scalars(competitor_stmt).all()

    rows: list[CompetitorComparisonRead] = []
    for competitor in competitors:
        competitor_membership = workspace_memberships.get(competitor.id) if workspace else None
        competitor_features = _workspace_member_features(competitor_membership, competitor)
        competitor_tools = _workspace_member_tools(competitor_membership, competitor)
        competitor_feature_map = {item.name.lower(): item for item in competitor_features}
        competitor_tool_map = {item.name.lower(): item for item in competitor_tools}

        competitor_only_features = [
            item for key, item in competitor_feature_map.items() if key not in baseline_feature_map
        ]
        competitor_only_tools = [
            item for key, item in competitor_tool_map.items() if key not in baseline_tool_map
        ]
        shared_features = [item for key, item in competitor_feature_map.items() if key in baseline_feature_map]
        shared_tools = [item for key, item in competitor_tool_map.items() if key in baseline_tool_map]
        relevant_news = _relevant_company_news_items(competitor)
        market_signal_count = len(relevant_news)

        feature_gap_score = round(len(competitor_only_features) * 1.8, 2)
        tool_gap_score = round(len(competitor_only_tools) * 1.2, 2)
        market_signal_score = round(market_signal_count * 0.15, 2)
        gap_score = round(feature_gap_score + tool_gap_score + market_signal_score, 2)

        news = sorted(
            relevant_news,
            key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        rows.append(
            CompetitorComparisonRead(
                company_id=competitor.id,
                company_name=competitor.company_name,
                linkedin_url=_resolve_company_linkedin_url(competitor),
                gap_score=gap_score,
                feature_gap_score=feature_gap_score,
                tool_gap_score=tool_gap_score,
                market_signal_score=market_signal_score,
                market_signal_count=market_signal_count,
                shared_feature_count=len(shared_features),
                shared_tool_count=len(shared_tools),
                competitor_only_features=sorted(competitor_only_features, key=lambda item: (item.category, item.name)),
                competitor_only_tools=sorted(competitor_only_tools, key=lambda item: (item.category, item.name)),
                shared_features=sorted(shared_features, key=lambda item: (item.category, item.name)),
                shared_tools=sorted(shared_tools, key=lambda item: (item.category, item.name)),
                top_news=[_serialize_news(item) for item in news[:5]],
            )
        )

    rows.sort(key=lambda row: row.gap_score, reverse=True)
    return ComparisonRead(
        analysis_workspace_id=workspace.id if workspace else None,
        analysis_workspace_name=workspace.name if workspace else None,
        workspace_status=workspace.status if workspace else None,
        workspace_status_message=workspace.status_message if workspace else None,
        target_version=workspace.target_version if workspace else None,
        focus_anchor_company_id=baseline.id,
        focus_anchor_company_name=baseline.company_name,
        baseline_company_id=baseline.id,
        baseline_company_name=baseline.company_name,
        baseline_features=baseline_features,
        baseline_tools=baseline_tools,
        competitors=rows,
    )


def _build_briefing(
    db: Session,
    baseline_company_id: int | None = None,
    analysis_workspace_id: int | None = None,
    focus_anchor_company_id: int | None = None,
) -> BriefingRead:
    comparison = _build_comparison(
        db=db,
        analysis_workspace_id=analysis_workspace_id,
        baseline_company_id=baseline_company_id,
        focus_anchor_company_id=focus_anchor_company_id,
        refresh_baseline=False,
        scrape_missing_baseline=False,
    )
    if comparison.baseline_company_id is None:
        workspace_label = comparison.analysis_workspace_name or "this workspace"
        status_message = comparison.workspace_status_message or "Autonomous Analyst Spinning Up..."
        return BriefingRead(
            date=_now(),
            analysis_workspace_id=comparison.analysis_workspace_id,
            analysis_workspace_name=comparison.analysis_workspace_name,
            workspace_status=comparison.workspace_status,
            workspace_status_message=comparison.workspace_status_message,
            target_version=comparison.target_version,
            focus_anchor_company_id=None,
            focus_anchor_company_name=None,
            baseline_company_id=None,
            baseline_company_name=comparison.baseline_company_name,
            summary=f"{workspace_label}: {status_message}",
            top_insights=[],
            urgent_signals=[],
            coverage_health=[],
            recommended_actions=[],
            onboarding=[
                OnboardingStepRead(
                    id="scope_market",
                    label="Scope market",
                    description="Identify the relevant enterprise software sector.",
                    status="done",
                ),
                OnboardingStepRead(
                    id="discover_vendors",
                    label="Discover vendors",
                    description="Find the initial 5-7 companies defining the market.",
                    status="active",
                ),
                OnboardingStepRead(
                    id="hydrate_entities",
                    label="Hydrate evidence",
                    description="Scrape vendor sources and extract features, tools, and claims.",
                    status="pending",
                ),
                OnboardingStepRead(
                    id="calculate_gaps",
                    label="Calculate gaps",
                    description="Select the initial focus anchor and rank competitor gaps.",
                    status="pending",
                ),
            ],
            ask_suggestions=[],
            totals={"companies": 0, "sources": 0, "features": 0, "tools": 0, "news": 0, "urgent_signals": 0},
        )
    baseline = db.scalar(
        select(CompanyProfile)
        .where(CompanyProfile.id == comparison.baseline_company_id)
        .options(
            selectinload(CompanyProfile.sources),
            selectinload(CompanyProfile.news_items),
            selectinload(CompanyProfile.claims),
        )
    )
    if not baseline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis target company not found")
    baseline_name = _safe_company_name(baseline.company_name, baseline.primary_domain)
    companies = db.scalars(
        select(CompanyProfile)
        .options(
            selectinload(CompanyProfile.sources),
            selectinload(CompanyProfile.news_items),
            selectinload(CompanyProfile.claims),
        )
        .order_by(CompanyProfile.source_count.desc(), CompanyProfile.company_name.asc())
    ).all()
    company_by_id = {company.id: company for company in companies}
    comparison_competitor_ids = {row.company_id for row in comparison.competitors}
    competitors = [company for company in companies if company.id in comparison_competitor_ids]

    insights: list[BriefingInsightRead] = []
    for row in comparison.competitors[:8]:
        company = company_by_id.get(row.company_id)
        if company is None:
            continue
        feature_count = len(row.competitor_only_features)
        tool_count = len(row.competitor_only_tools)
        if feature_count + tool_count == 0 and row.market_signal_count == 0:
            continue

        evidence = _recent_company_evidence(company, limit=3)
        claim_count = _count_high_confidence_claims(company)
        if feature_count + tool_count > 0:
            impact = _impact_from_score(row.gap_score)
            named_signals = _signal_names([*row.competitor_only_features, *row.competitor_only_tools])
            insight_id = f"gap-{row.company_id}"
            insights.append(
                BriefingInsightRead(
                    id=insight_id,
                    insight_type="market_gap",
                    headline=f"{row.company_name} is creating pressure around {named_signals}",
                    summary=(
                        f"{row.company_name} shows {feature_count} differentiated features and {tool_count} "
                        f"differentiated tools against the {baseline_name} baseline."
                    ),
                    competitor_id=row.company_id,
                    competitor_name=row.company_name,
                    impact=impact,
                    confidence=_clamp_confidence(0.58 + min(row.gap_score, 20) / 55 + min(claim_count, 6) * 0.025),
                    urgency=_urgency_from_impact(impact),
                    recommended_action=(
                        f"Review {baseline_name} positioning and roadmap coverage for {named_signals}; prepare a counter "
                        f"message for deals where {row.company_name} appears."
                    ),
                    why_it_matters=(
                        "This is the clearest product or messaging delta currently visible from public evidence."
                    ),
                    evidence=evidence,
                )
            )
        elif row.market_signal_count > 0:
            impact = _impact_from_score(row.market_signal_score + 4)
            insight_id = f"momentum-{row.company_id}"
            insights.append(
                BriefingInsightRead(
                    id=insight_id,
                    insight_type="market_momentum",
                    headline=f"{row.company_name} has elevated market activity",
                    summary=f"{row.market_signal_count} relevant market signals were found from news and connectors.",
                    competitor_id=row.company_id,
                    competitor_name=row.company_name,
                    impact=impact,
                    confidence=_clamp_confidence(0.55 + min(row.market_signal_count, 12) * 0.035),
                    urgency=_urgency_from_impact(impact),
                    recommended_action=(
                        f"Scan {row.company_name}'s latest evidence for launch, hiring, or positioning changes before "
                        "the next competitive review."
                    ),
                    why_it_matters="A rising signal volume often precedes a launch, campaign, partnership, or narrative shift.",
                    evidence=evidence,
                )
            )

    seen_insight_companies = {insight.competitor_id for insight in insights if insight.competitor_id}
    momentum_candidates = sorted(
        competitors,
        key=lambda company: len(_relevant_company_news_items(company)),
        reverse=True,
    )
    for company in momentum_candidates:
        if len(insights) >= 8:
            break
        if company.id in seen_insight_companies:
            continue
        news_count = len(_relevant_company_news_items(company))
        if news_count < 2:
            continue
        impact = _impact_from_score(news_count)
        insights.append(
            BriefingInsightRead(
                id=f"momentum-{company.id}",
                insight_type="market_momentum",
                headline=f"{_safe_company_name(company.company_name, company.primary_domain)} is showing fresh activity",
                summary=f"{news_count} relevant news or connector signals are available for inspection.",
                competitor_id=company.id,
                competitor_name=_safe_company_name(company.company_name, company.primary_domain),
                impact=impact,
                confidence=_clamp_confidence(0.54 + min(news_count, 10) * 0.035),
                urgency=_urgency_from_impact(impact),
                recommended_action="Open the evidence drawer and verify whether the activity maps to a launch, campaign, or partner move.",
                why_it_matters="Fresh activity is most useful when it is reviewed before a sales cycle or roadmap decision.",
                evidence=_recent_company_evidence(company, limit=3),
            )
        )

    coverage_health = [_company_coverage_health(company) for company in competitors]
    coverage_health.sort(key=lambda item: (item.coverage_score, item.company_name))
    if not insights and competitors:
        for item in coverage_health[:3]:
            company = company_by_id.get(item.company_id)
            if company is None:
                continue
            insights.append(
                BriefingInsightRead(
                    id=f"coverage-{item.company_id}",
                    insight_type="coverage_gap",
                    headline=f"{item.company_name} needs better evidence coverage",
                    summary=item.note,
                    competitor_id=item.company_id,
                    competitor_name=item.company_name,
                    impact="medium" if item.status == "thin" else "low",
                    confidence=0.64,
                    urgency="monitor",
                    recommended_action=f"Add {', '.join(item.missing_sources[:2]) or 'direct source evidence'} for {item.company_name}.",
                    why_it_matters="Strategic recommendations should not be trusted until the system has direct and recent evidence.",
                    evidence=_recent_company_evidence(company, limit=2),
                )
            )

    insights.sort(
        key=lambda item: (
            {"high": 3, "medium": 2, "low": 1}.get(item.impact, 0),
            item.confidence,
            len(item.evidence),
        ),
        reverse=True,
    )
    top_insights = insights[:5]
    urgent_signals = [item for item in insights if item.impact == "high"][:3] or top_insights[:3]
    recommendations = _recommendations_from_insights(top_insights)

    total_news = sum(len(_relevant_company_news_items(company)) for company in competitors)
    total_features = sum(len(_load_features(company.feature_set_json)) for company in competitors)
    total_tools = sum(len(_load_tools(company.tool_set_json)) for company in competitors)
    totals = {
        "companies": len(competitors),
        "sources": sum(company.source_count for company in competitors),
        "features": total_features,
        "tools": total_tools,
        "news": total_news,
        "urgent_signals": len(urgent_signals),
    }
    onboarding = _build_onboarding_steps(
        competitor_count=len(competitors),
        source_count=totals["sources"],
        insight_count=len(top_insights),
        baseline=baseline,
        coverage_health=coverage_health,
    )

    if not competitors:
        summary = f"Add three competitors around {baseline_name} to generate the first strategic briefing."
    elif top_insights:
        summary = f"{len(top_insights)} priority insights are ready for {baseline_name} from {len(competitors)} tracked competitors."
    else:
        summary = f"Competitors are tracked for {baseline_name}, but more direct evidence is needed before strategy recommendations are useful."

    return BriefingRead(
        date=_now(),
        analysis_workspace_id=comparison.analysis_workspace_id,
        analysis_workspace_name=comparison.analysis_workspace_name,
        workspace_status=comparison.workspace_status,
        workspace_status_message=comparison.workspace_status_message,
        target_version=comparison.target_version,
        focus_anchor_company_id=baseline.id,
        focus_anchor_company_name=baseline_name,
        baseline_company_id=baseline.id,
        baseline_company_name=baseline_name,
        summary=summary,
        top_insights=top_insights,
        urgent_signals=urgent_signals,
        coverage_health=coverage_health[:8],
        recommended_actions=recommendations,
        onboarding=onboarding,
        ask_suggestions=[
            "What changed this week across my competitors?",
            f"Which competitor has the largest product gap against {baseline_name}?",
            "Which companies need better evidence coverage?",
            "Show evidence behind the top priority signal.",
        ],
        totals=totals,
    )


@app.get("/briefing", response_model=BriefingRead)
def get_briefing(
    analysis_workspace_id: int | None = Query(
        default=None,
        description="Analysis workspace id. When provided, the workspace company pool defines the analysis scope.",
    ),
    baseline_company_id: int | None = Query(
        default=None,
        description="Company profile id to use as the analysis target. Defaults to the Concentric AI baseline.",
    ),
    focus_anchor_company_id: int | None = Query(
        default=None,
        description="Company profile id to use as the focus anchor inside a workspace.",
    ),
    db: Session = Depends(get_db),
) -> BriefingRead:
    return _build_briefing(
        db=db,
        baseline_company_id=baseline_company_id,
        analysis_workspace_id=analysis_workspace_id,
        focus_anchor_company_id=focus_anchor_company_id,
    )


@app.post("/ai/ask", response_model=AskConcentricResponse)
def ask_concentric_ai(request: AskConcentricRequest, db: Session = Depends(get_db)) -> AskConcentricResponse:
    briefing = _build_briefing(
        db=db,
        baseline_company_id=request.baseline_company_id,
        analysis_workspace_id=request.analysis_workspace_id,
        focus_anchor_company_id=request.focus_anchor_company_id,
    )
    question = request.question.strip().lower()
    insight_pool = list({insight.id: insight for insight in [*briefing.top_insights, *briefing.urgent_signals]}.values())
    selected: BriefingInsightRead | None = None

    for insight in insight_pool:
        competitor_name = (insight.competitor_name or "").lower()
        if competitor_name and competitor_name in question:
            selected = insight
            break
    if selected is None and any(token in question for token in ["gap", "lacks", "behind", "ahead"]):
        selected = next((insight for insight in insight_pool if insight.insight_type == "market_gap"), None)
    if selected is None and any(token in question for token in ["coverage", "source", "evidence quality"]):
        weak_coverage = briefing.coverage_health[0] if briefing.coverage_health else None
        if weak_coverage:
            return AskConcentricResponse(
                answer=(
                    f"{weak_coverage.company_name} has the weakest evidence coverage right now "
                    f"({weak_coverage.coverage_score}/100)."
                ),
                why_it_matters=weak_coverage.note,
                evidence=[],
                recommended_next_step=(
                    f"Add {', '.join(weak_coverage.missing_sources[:2]) or 'more direct evidence'} "
                    f"for {weak_coverage.company_name}."
                ),
                confidence=0.7,
            )
    if selected is None:
        selected = insight_pool[0] if insight_pool else None

    if selected is None:
        return AskConcentricResponse(
            answer="I need at least one competitor source before I can answer with evidence.",
            why_it_matters="The analyst layer only responds from structured company, source, news, and gap data.",
            evidence=[],
            recommended_next_step="Add three competitor websites or product pages to generate the first briefing.",
            confidence=0.5,
        )

    return AskConcentricResponse(
        answer=selected.summary,
        why_it_matters=selected.why_it_matters,
        evidence=selected.evidence,
        recommended_next_step=selected.recommended_action,
        confidence=selected.confidence,
    )


@app.get("/comparison", response_model=ComparisonRead)
def get_comparison(
    analysis_workspace_id: int | None = Query(
        default=None,
        description="Analysis workspace id. When provided, the workspace company pool defines the analysis scope.",
    ),
    baseline_company_id: int | None = Query(
        default=None,
        description="Company profile id to use as the analysis target. Defaults to the Concentric AI baseline.",
    ),
    focus_anchor_company_id: int | None = Query(
        default=None,
        description="Company profile id to use as the focus anchor inside a workspace.",
    ),
    refresh_baseline: bool = Query(
        default=False,
        description="When true, refreshes the selected analysis target before comparison. Default is read-only for API stability.",
    ),
    db: Session = Depends(get_db),
) -> ComparisonRead:
    return _build_comparison(
        db=db,
        analysis_workspace_id=analysis_workspace_id,
        baseline_company_id=baseline_company_id,
        focus_anchor_company_id=focus_anchor_company_id,
        refresh_baseline=refresh_baseline,
    )
