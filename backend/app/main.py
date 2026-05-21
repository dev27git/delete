from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from .database import Base, engine, get_db
from .enrichment import fetch_enrichment_news, list_enrichment_connectors
from .models import CompanyNews, CompanyProfile, CompanySource
from .schemas import (
    CompanyDetailRead,
    CompanyNewsRead,
    CompanySummaryRead,
    ComparisonRead,
    CompetitiveURLCreate,
    CompetitiveURLRead,
    CompetitorComparisonRead,
    EnrichmentConnectorRead,
    FeatureSignal,
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
    return CompetitiveURLRead(
        id=source.id,
        url=source.source_url,
        domain=source.source_domain,
        source_type=source.source_type,
        status="partial" if source.last_error and source.company_id else "failed" if source.last_error else "scraped",
        company_id=source.company_id,
        company_name=source.company.company_name if source.company else source.detected_company_name,
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


def _serialize_company_summary(company: CompanyProfile) -> CompanySummaryRead:
    linkedin_url = _resolve_company_linkedin_url(company)
    return CompanySummaryRead(
        id=company.id,
        company_name=company.company_name,
        primary_domain=company.primary_domain,
        website_url=company.website_url,
        linkedin_url=linkedin_url,
        description=company.description,
        source_count=company.source_count,
        news_count=company.news_count,
        linkedin_news_count=_count_company_news(company, source="linkedin_news_rss"),
        enrichment_news_count=_count_company_news_prefix(company, prefix="enrichment:"),
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


def _resolve_company_linkedin_url(company: CompanyProfile) -> str | None:
    for source in company.sources:
        explicit = extract_linkedin_company_url(source.source_url)
        if explicit:
            return explicit
    return derive_linkedin_company_url(company.company_name)


def _resolve_or_create_company(db: Session, company_name: str, domain: str, source_url: str) -> CompanyProfile:
    company_key = normalize_company_key(company_name) or normalize_company_key(domain)
    if not company_key:
        company_key = normalize_company_key(source_url)

    company = db.scalar(select(CompanyProfile).where(CompanyProfile.company_key == company_key))
    if company:
        return company

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
    added_counts: dict[str, int] = {}

    try:
        news_items = fetch_company_news(company_name=company.company_name, domain=company.primary_domain)
        added_counts["google_news_rss"] = _add_news_items(
            db=db,
            company=company,
            items=news_items,
            source="google_news_rss",
        )
    except Exception:
        added_counts["google_news_rss"] = 0

    try:
        linkedin_news = fetch_linkedin_news(company_name=company.company_name, linkedin_url=linkedin_url)
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
    added_counts: dict[str, int] = {}
    try:
        connector_results = fetch_enrichment_news(company_name=company.company_name, domain=company.primary_domain)
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


def _scrape_and_merge_source(db: Session, source: CompanySource) -> None:
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
        )
        source.company_id = company.id
        db.flush()
        _recompute_company_profile(db, company)
        _refresh_company_news(db, company)
        _refresh_company_enrichment(db, company)
        return

    source.source_url = scrape.final_url
    source.source_domain = extract_domain(scrape.final_url)
    source.source_type = scrape.source_type
    source.detected_company_name = scrape.company_name
    source.http_status = scrape.http_status
    source.page_title = scrape.page_title
    source.meta_description = scrape.meta_description
    source.summary = scrape.summary
    source.published_at = scrape.published_at
    source.headings_json = json.dumps(scrape.headings, ensure_ascii=True)
    source.extracted_features_json = _dump_features(_dedupe_feature_hits(scrape.detected_features))
    source.extracted_tools_json = _dump_tools(_dedupe_tool_hits(scrape.detected_tools))
    source.confidence = scrape.confidence

    company = _resolve_or_create_company(
        db=db,
        company_name=scrape.company_name,
        domain=source.source_domain,
        source_url=scrape.final_url,
    )
    source.company_id = company.id
    db.flush()

    _recompute_company_profile(db, company)
    _refresh_company_news(db, company)
    _refresh_company_enrichment(db, company)


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

    _scrape_and_merge_source(db=db, source=source)
    db.commit()
    db.refresh(source)
    return _serialize_source(source)


@app.post("/competitive-urls/{source_id}/rescrape", response_model=CompetitiveURLRead)
def rescrape_competitive_url(source_id: int, db: Session = Depends(get_db)) -> CompetitiveURLRead:
    source = db.get(CompanySource, source_id)
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="URL not found")

    _scrape_and_merge_source(db=db, source=source)
    if source.company_id:
        company = db.get(CompanyProfile, source.company_id)
        if company:
            _recompute_company_profile(db, company)
            _refresh_company_news(db, company)

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
            _refresh_company_news(db, company)
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
    )


@app.post("/companies/{company_id}/refresh-news", response_model=CompanyDetailRead)
def refresh_company_news(company_id: int, db: Session = Depends(get_db)) -> CompanyDetailRead:
    company = db.get(CompanyProfile, company_id)
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    _refresh_company_news(db, company)
    db.commit()
    return get_company_detail(company_id=company.id, db=db)


@app.post("/companies/{company_id}/refresh-enrichment", response_model=CompanyDetailRead)
def refresh_company_enrichment(company_id: int, db: Session = Depends(get_db)) -> CompanyDetailRead:
    company = db.get(CompanyProfile, company_id)
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    _refresh_company_enrichment(db, company)
    db.commit()
    return get_company_detail(company_id=company.id, db=db)


@app.get("/comparison", response_model=ComparisonRead)
def get_comparison(db: Session = Depends(get_db)) -> ComparisonRead:
    baseline = _ensure_baseline_profile(db)
    _recompute_company_profile(db, baseline)
    _refresh_company_news(db, baseline)
    db.commit()

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

        gap_score = round(
            len(competitor_only_features) * 1.8
            + len(competitor_only_tools) * 1.2
            + (competitor.news_count * 0.15),
            2,
        )

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
