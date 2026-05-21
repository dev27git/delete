from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus

from .scraper import NewsItem, fetch_news_feed

MAX_ITEMS_PER_CONNECTOR = 6


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


def fetch_enrichment_news(company_name: str, domain: str | None = None) -> dict[str, list[NewsItem]]:
    results: dict[str, list[NewsItem]] = {}
    for connector in CONNECTORS:
        if not connector.enabled_by_default or connector.requires_api_key:
            continue
        try:
            feed_url = _connector_feed_url(connector=connector, company_name=company_name, domain=domain)
            results[connector.id] = fetch_news_feed(feed_url=feed_url)[:MAX_ITEMS_PER_CONNECTOR]
        except Exception:
            results[connector.id] = []
    return results
