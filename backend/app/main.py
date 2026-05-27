from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Select, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, selectinload

from .database import Base, SessionLocal, engine, get_db
from .discovery import discover_competitor_candidates, list_competitor_catalog
from .enrichment import fetch_enrichment_news, list_enrichment_connectors
from .models import (
    CompanyClaim,
    CompanyMergeReview,
    CompanyNews,
    CompanyProfile,
    CompanySource,
    IngestionJob,
)
from .schemas import (
    AutoDiscoverResponse,
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
    ToolSignal,
)
from .scraper import (
    FeatureHit,
    ToolHit,
    derive_linkedin_company_url,
    extract_domain,
    extract_linkedin_company_url,
    fetch_company_news,
    fetch_linkedin_news,
    infer_company_name_from_domain,
    normalize_company_key,
    normalize_url,
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

app = FastAPI(title="Concentric Competitive Intelligence API", version="0.3.0")

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
    _start_scheduler()


@app.on_event("shutdown")
def on_shutdown() -> None:
    _stop_scheduler()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
        detected_features=_load_features(source.extracted_features_json),
        detected_tools=_load_tools(source.extracted_tools_json),
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


def _serialize_company_summary(company: CompanyProfile) -> CompanySummaryRead:
    linkedin_url = _resolve_company_linkedin_url(company)
    display_company_name = _safe_company_name(company.company_name, company.primary_domain)
    return CompanySummaryRead(
        id=company.id,
        company_name=display_company_name,
        primary_domain=company.primary_domain,
        website_url=company.website_url,
        linkedin_url=linkedin_url,
        description=company.description,
        source_count=company.source_count,
        news_count=company.news_count,
        linkedin_news_count=_count_company_news(company, source="linkedin_news_rss"),
        enrichment_news_count=_count_company_news_prefix(company, prefix="enrichment:"),
        high_confidence_claim_count=_count_high_confidence_claims(company),
        news_source_counts=_company_news_source_counts(company),
        last_refreshed_at=company.last_refreshed_at,
        features=_load_features(company.feature_set_json),
        tools=_load_tools(company.tool_set_json),
    )


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
        if item.source == source:
            count += 1
    return count


def _count_company_news_prefix(company: CompanyProfile, prefix: str) -> int:
    count = 0
    for item in company.news_items:
        if item.source.startswith(prefix):
            count += 1
    return count


def _company_news_source_counts(company: CompanyProfile) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in company.news_items:
        counts[item.source] = counts.get(item.source, 0) + 1
    return dict(sorted(counts.items()))


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
    features = _load_features(source.extracted_features_json)
    tools = _load_tools(source.extracted_tools_json)
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
    db.flush()

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


def _resolve_company_linkedin_url(company: CompanyProfile) -> str | None:
    for source in company.sources:
        explicit = extract_linkedin_company_url(source.source_url)
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
        merged_features = _merge_feature_sets(merged_features, _load_features(source.extracted_features_json))
        merged_tools = _merge_tool_sets(merged_tools, _load_tools(source.extracted_tools_json))

    company.feature_set_json = _dump_features(merged_features)
    company.tool_set_json = _dump_tools(merged_tools)
    company.description = best_source.summary or best_source.meta_description or company.description
    if "linkedin.com" not in best_source.source_domain:
        company.primary_domain = best_source.source_domain or company.primary_domain
        company.website_url = best_source.source_url or company.website_url


def _add_news_items(db: Session, company: CompanyProfile, items: list[Any], source: str) -> int:
    added = 0
    for item in items:
        article_url = item.article_url.strip()
        if not article_url:
            continue
        exists = db.scalar(select(CompanyNews).where(CompanyNews.article_url == article_url))
        if exists:
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


def _ensure_baseline_profile(db: Session) -> CompanyProfile:
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
def list_competitive_urls(db: Session = Depends(get_db)) -> list[CompetitiveURLRead]:
    stmt: Select[Any] = (
        select(CompanySource)
        .options(selectinload(CompanySource.company))
        .order_by(CompanySource.updated_at.desc())
    )
    sources = db.scalars(stmt).all()
    return [_serialize_source(source) for source in sources]


@app.post("/competitive-urls", response_model=CompetitiveURLRead, status_code=status.HTTP_201_CREATED)
def add_competitive_url(payload: CompetitiveURLCreate, db: Session = Depends(get_db)) -> CompetitiveURLRead:
    normalized = normalize_url(payload.url)
    if not normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="URL is required")
    domain = extract_domain(normalized)
    if not domain:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid URL")

    existing = db.scalar(select(CompanySource).where(CompanySource.source_url == normalized))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="URL already exists")

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
    db.commit()
    db.refresh(source)
    return _serialize_source(source)


@app.post("/competitors/auto-discover", response_model=AutoDiscoverResponse)
def auto_discover_competitors(
    max_candidates: int = Query(default=30, ge=5, le=200),
    include_news: bool = Query(default=True),
    refresh_market_signals: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> AutoDiscoverResponse:
    candidates = discover_competitor_candidates(max_count=max_candidates, include_news=include_news)
    existing_sources = db.scalars(select(CompanySource)).all()
    existing_domains = {_canonical_domain(source.source_url) for source in existing_sources}

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
        db.flush()

        created_source_id = source.id
        source = _scrape_and_merge_source(
            db=db,
            source=source,
            refresh_market_signals=refresh_market_signals,
        )
        existing_domains.add(domain)
        existing_domains.add(_canonical_domain(source.source_url))
        if source.id != created_source_id:
            skipped_existing += 1
            continue

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
    source = db.get(CompanySource, source_id)
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="URL not found")

    source = _scrape_and_merge_source(db=db, source=source)

    db.commit()
    db.refresh(source)
    return _serialize_source(source)


@app.delete("/competitive-urls/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_competitive_url(source_id: int, db: Session = Depends(get_db)) -> Response:
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
        .options(
            selectinload(CompanyProfile.sources),
            selectinload(CompanyProfile.news_items),
            selectinload(CompanyProfile.claims),
        )
        .order_by(CompanyProfile.source_count.desc(), CompanyProfile.company_name.asc())
    ).all()
    return [_serialize_company_summary(company) for company in companies]


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
        company.news_items,
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
    company = db.get(CompanyProfile, company_id)
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    _run_company_refresh_job(db=db, company=company, run_mode="manual", refresh_news=True, refresh_enrichment=False)
    db.commit()
    return get_company_detail(company_id=company.id, db=db)


@app.post("/companies/{company_id}/refresh-enrichment", response_model=CompanyDetailRead)
def refresh_company_enrichment(company_id: int, db: Session = Depends(get_db)) -> CompanyDetailRead:
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


@app.get("/comparison", response_model=ComparisonRead)
def get_comparison(
    refresh_baseline: bool = Query(
        default=False,
        description="When true, refreshes Concentric baseline news before comparison. Default is read-only for API stability.",
    ),
    db: Session = Depends(get_db),
) -> ComparisonRead:
    baseline = _ensure_baseline_profile(db)
    if refresh_baseline:
        try:
            _recompute_company_profile(db, baseline)
            _refresh_company_news(db, baseline)
            db.commit()
        except OperationalError:
            # Keep comparison endpoint available even when concurrent write traffic temporarily locks SQLite.
            db.rollback()
            baseline = db.get(CompanyProfile, baseline.id) or baseline

    baseline_features = _load_features(baseline.feature_set_json)
    baseline_tools = _load_tools(baseline.tool_set_json)
    baseline_feature_map = {item.name.lower(): item for item in baseline_features}
    baseline_tool_map = {item.name.lower(): item for item in baseline_tools}

    competitors = db.scalars(
        select(CompanyProfile)
        .where(CompanyProfile.id != baseline.id)
        .options(
            selectinload(CompanyProfile.sources),
            selectinload(CompanyProfile.news_items),
            selectinload(CompanyProfile.claims),
        )
        .order_by(CompanyProfile.source_count.desc())
    ).all()

    rows: list[CompetitorComparisonRead] = []
    for competitor in competitors:
        competitor_features = _load_features(competitor.feature_set_json)
        competitor_tools = _load_tools(competitor.tool_set_json)
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

        feature_gap_score = round(len(competitor_only_features) * 1.8, 2)
        tool_gap_score = round(len(competitor_only_tools) * 1.2, 2)
        market_signal_score = round(competitor.news_count * 0.15, 2)
        gap_score = round(feature_gap_score + tool_gap_score + market_signal_score, 2)

        news = sorted(
            competitor.news_items,
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
                market_signal_count=competitor.news_count,
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
        baseline_company_name=baseline.company_name,
        baseline_features=baseline_features,
        baseline_tools=baseline_tools,
        competitors=rows,
    )
