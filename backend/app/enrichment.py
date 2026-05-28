from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote_plus

from .scraper import NewsItem, fetch_news_feed

MAX_ITEMS_PER_CONNECTOR = 6
MIN_CONNECTOR_RELEVANCE_SCORE = 0.55

GENERIC_IDENTITY_TERMS = {
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
}


@dataclass(frozen=True, slots=True)
class EnrichmentConnector:
    id: str
    name: str
    category: str
    method: str
    site_domain: str
    query_terms: tuple[str, ...] = ()
    requires_api_key: bool = False
    enabled_by_default: bool = True


CONNECTORS: tuple[EnrichmentConnector, ...] = (
    EnrichmentConnector(
        id="owasp_genai_security",
        name="OWASP GenAI Security",
        category="Security Framework",
        method="source_scoped_google_news",
        site_domain="genai.owasp.org",
        query_terms=("LLM", "GenAI", "security"),
    ),
    EnrichmentConnector(
        id="nist_ai_security",
        name="NIST AI Security",
        category="Security Framework",
        method="source_scoped_google_news",
        site_domain="nist.gov",
        query_terms=("AI", "risk", "security", "framework"),
    ),
    EnrichmentConnector(
        id="cisa_ai_security",
        name="CISA AI Security",
        category="Security Guidance",
        method="source_scoped_google_news",
        site_domain="cisa.gov",
        query_terms=("AI", "security", "guidance"),
    ),
    EnrichmentConnector(
        id="mit_technology_review_ai",
        name="MIT Technology Review AI",
        category="AI News",
        method="source_scoped_google_news",
        site_domain="technologyreview.com",
        query_terms=("AI", "security"),
    ),
    EnrichmentConnector(
        id="techcrunch_ai",
        name="TechCrunch AI",
        category="AI News",
        method="source_scoped_google_news",
        site_domain="techcrunch.com",
        query_terms=("AI", "security"),
    ),
    EnrichmentConnector(
        id="palo_alto_unit_42",
        name="Palo Alto Unit 42",
        category="Threat Research",
        method="source_scoped_google_news",
        site_domain="unit42.paloaltonetworks.com",
        query_terms=("AI", "security", "threat"),
    ),
    EnrichmentConnector(
        id="google_security_blog",
        name="Google Security Blog",
        category="Security Research",
        method="source_scoped_google_news",
        site_domain="security.googleblog.com",
        query_terms=("AI", "security", "LLM"),
    ),
    EnrichmentConnector(
        id="aws_security_blog",
        name="AWS Security Blog",
        category="Security Research",
        method="source_scoped_google_news",
        site_domain="aws.amazon.com/blogs/security",
        query_terms=("AI", "security", "cloud"),
    ),
    EnrichmentConnector(
        id="cloudflare_blog",
        name="Cloudflare Blog",
        category="Security Research",
        method="source_scoped_google_news",
        site_domain="blog.cloudflare.com",
        query_terms=("AI", "security", "bots"),
    ),
    EnrichmentConnector(
        id="mandiant_threat_intelligence",
        name="Mandiant Threat Intelligence",
        category="Threat Research",
        method="source_scoped_google_news",
        site_domain="cloud.google.com/blog/topics/threat-intelligence",
        query_terms=("AI", "security", "threat"),
    ),
    EnrichmentConnector(
        id="dark_reading_ai_security",
        name="Dark Reading AI Security",
        category="Security News",
        method="source_scoped_google_news",
        site_domain="darkreading.com",
        query_terms=("AI", "security", "LLM"),
    ),
    EnrichmentConnector(
        id="the_hacker_news_ai_security",
        name="The Hacker News AI Security",
        category="Security News",
        method="source_scoped_google_news",
        site_domain="thehackernews.com",
        query_terms=("AI", "security", "LLM"),
    ),
    EnrichmentConnector(
        id="microsoft_security_blog",
        name="Microsoft Security Blog",
        category="Security Research",
        method="source_scoped_google_news",
        site_domain="microsoft.com",
        query_terms=("security", "AI", "blog"),
    ),
    EnrichmentConnector(
        id="github_ai_security",
        name="GitHub AI Security Topics",
        category="Developer Signal",
        method="source_scoped_google_news",
        site_domain="github.com",
        query_terms=('"AI security"', '"LLM security"'),
    ),
    EnrichmentConnector(
        id="snyk_ai_security",
        name="Snyk AI Security",
        category="Developer Security",
        method="source_scoped_google_news",
        site_domain="snyk.io/blog",
        query_terms=("AI", "security", "open source"),
    ),
    EnrichmentConnector(
        id="semgrep_ai_security",
        name="Semgrep AI Security",
        category="Developer Security",
        method="source_scoped_google_news",
        site_domain="semgrep.dev/blog",
        query_terms=("AI", "security", "code"),
    ),
    EnrichmentConnector(
        id="hugging_face",
        name="Hugging Face",
        category="AI Ecosystem",
        method="source_scoped_google_news",
        site_domain="huggingface.co",
        query_terms=("models", "AI", "security"),
    ),
    EnrichmentConnector(
        id="the_rundown_ai",
        name="The Rundown AI",
        category="AI News",
        method="source_scoped_google_news",
        site_domain="therundown.ai",
        query_terms=("AI", "security"),
    ),
    EnrichmentConnector(
        id="venturebeat_ai",
        name="VentureBeat AI",
        category="AI News",
        method="source_scoped_google_news",
        site_domain="venturebeat.com/ai",
        query_terms=("AI", "security", "enterprise"),
    ),
    EnrichmentConnector(
        id="siliconangle_ai",
        name="SiliconANGLE AI",
        category="AI News",
        method="source_scoped_google_news",
        site_domain="siliconangle.com",
        query_terms=("AI", "security", "enterprise"),
    ),
    EnrichmentConnector(
        id="product_hunt_ai",
        name="Product Hunt AI",
        category="Launch Signal",
        method="source_scoped_google_news",
        site_domain="producthunt.com",
        query_terms=("AI", "launch"),
    ),
    EnrichmentConnector(
        id="crunchbase_ai",
        name="Crunchbase AI",
        category="Market Data",
        method="source_scoped_google_news",
        site_domain="crunchbase.com",
        query_terms=("AI", "funding"),
    ),
)


def list_enrichment_connectors() -> list[EnrichmentConnector]:
    return list(CONNECTORS)


def _connector_feed_url(connector: EnrichmentConnector, company_name: str, domain: str | None) -> str:
    identity = f'"{company_name}"'
    if domain:
        clean_domain = domain.removeprefix("www.")
        identity = f'("{company_name}" OR "{clean_domain}")'
    terms = [identity, f"site:{connector.site_domain}", *connector.query_terms]
    query = quote_plus(" ".join(terms))
    return f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


def _normalize_for_match(value: str | None) -> str:
    if not value:
        return ""
    normalized = re.sub(r"[^a-z0-9.]+", " ", value.lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _domain_identity_terms(domain: str | None) -> list[str]:
    if not domain:
        return []
    clean_domain = _normalize_for_match(domain.removeprefix("www."))
    terms = [clean_domain] if clean_domain else []
    domain_root = clean_domain.split(".", 1)[0]
    if len(domain_root) >= 4 and domain_root not in GENERIC_IDENTITY_TERMS:
        terms.append(domain_root)
    return terms


def _company_identity_terms(company_name: str, domain: str | None) -> list[str]:
    normalized_name = _normalize_for_match(company_name)
    terms = [normalized_name] if normalized_name else []
    terms.extend(
        token
        for token in normalized_name.split()
        if len(token) >= 4 and token not in GENERIC_IDENTITY_TERMS
    )
    terms.extend(_domain_identity_terms(domain))
    return list(dict.fromkeys(term for term in terms if term))


def _query_relevance_terms(connector: EnrichmentConnector) -> list[str]:
    terms = [_normalize_for_match(term.strip('"')) for term in connector.query_terms]
    return [term for term in terms if term]


def _connector_source_terms(connector: EnrichmentConnector) -> list[str]:
    site_domain = _normalize_for_match(connector.site_domain.removeprefix("www."))
    terms = [site_domain] if site_domain else []
    source_root = site_domain.split(".", 1)[0]
    if source_root:
        terms.append(source_root)
    normalized_name = _normalize_for_match(connector.name)
    if normalized_name:
        terms.append(normalized_name)
    return list(dict.fromkeys(term for term in terms if term))


def _contains_term(text: str, term: str) -> bool:
    if not text or not term:
        return False
    if " " in term or "." in term:
        return term in text
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def _connector_item_relevance_score(
    connector: EnrichmentConnector,
    item: NewsItem,
    company_name: str,
    domain: str | None,
) -> float:
    title_summary = _normalize_for_match(f"{item.title} {item.summary or ''}")
    full_text = _normalize_for_match(
        f"{item.title} {item.summary or ''} {item.publisher or ''} {item.article_url}"
    )

    identity_terms = _company_identity_terms(company_name=company_name, domain=domain)
    if not any(_contains_term(full_text, term) for term in identity_terms):
        return 0.0

    identity_score = 0.45
    if any(_contains_term(title_summary, term) for term in identity_terms):
        identity_score = 0.55

    source_score = 0.0
    if any(_contains_term(full_text, term) for term in _connector_source_terms(connector)):
        source_score = 0.25

    topic_score = 0.0
    if any(_contains_term(title_summary, term) for term in _query_relevance_terms(connector)):
        topic_score = 0.2

    summary_score = 0.05 if item.summary else 0.0
    return min(identity_score + source_score + topic_score + summary_score, 1.0)


def _filter_relevant_items(
    connector: EnrichmentConnector,
    items: list[NewsItem],
    company_name: str,
    domain: str | None,
) -> list[NewsItem]:
    scored_items = [
        (_connector_item_relevance_score(connector, item, company_name, domain), item)
        for item in items
    ]
    relevant_items = [
        item
        for score, item in scored_items
        if score >= MIN_CONNECTOR_RELEVANCE_SCORE
    ]
    return relevant_items[:MAX_ITEMS_PER_CONNECTOR]


def fetch_enrichment_news(company_name: str, domain: str | None = None) -> dict[str, list[NewsItem]]:
    results: dict[str, list[NewsItem]] = {}
    for connector in CONNECTORS:
        if not connector.enabled_by_default or connector.requires_api_key:
            continue
        try:
            feed_url = _connector_feed_url(connector=connector, company_name=company_name, domain=domain)
            items = fetch_news_feed(feed_url=feed_url)
            results[connector.id] = _filter_relevant_items(
                connector=connector,
                items=items,
                company_name=company_name,
                domain=domain,
            )
        except Exception:
            results[connector.id] = []
    return results
