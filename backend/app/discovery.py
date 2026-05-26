from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus

from .scraper import extract_domain, fetch_news_feed, normalize_url


@dataclass(frozen=True, slots=True)
class CompetitorCandidate:
    company_name: str
    url: str
    segment: str
    source: str


COMPETITOR_CATALOG: tuple[CompetitorCandidate, ...] = (
    CompetitorCandidate("Cyera", "https://www.cyera.com/", "DSPM", "catalog"),
    CompetitorCandidate("Sentra", "https://www.sentra.io/", "DSPM", "catalog"),
    CompetitorCandidate("BigID", "https://bigid.com/", "DSPM", "catalog"),
    CompetitorCandidate("Securiti", "https://securiti.ai/", "DSPM", "catalog"),
    CompetitorCandidate("Symmetry Systems", "https://www.symmetry-systems.com/", "DSPM", "catalog"),
    CompetitorCandidate("Varonis", "https://www.varonis.com/", "Data Security", "catalog"),
    CompetitorCandidate("Rubrik", "https://www.rubrik.com/", "Data Security", "catalog"),
    CompetitorCandidate("IBM Guardium", "https://www.ibm.com/guardium", "Data Security", "catalog"),
    CompetitorCandidate("OpenText", "https://www.opentext.com/products/data-security", "Data Security", "catalog"),
    CompetitorCandidate("Thales", "https://cpl.thalesgroup.com/data-security", "Data Security", "catalog"),
    CompetitorCandidate("Microsoft Purview", "https://www.microsoft.com/en-us/security/business/microsoft-purview", "Data Security", "catalog"),
    CompetitorCandidate("Wiz", "https://www.wiz.io/", "Cloud Security", "catalog"),
    CompetitorCandidate("Forcepoint", "https://www.forcepoint.com/", "Data Security", "catalog"),
    CompetitorCandidate("Veza", "https://veza.com/", "Identity Security", "catalog"),
    CompetitorCandidate("Cyberhaven", "https://www.cyberhaven.com/", "AI and Data Security", "catalog"),
    CompetitorCandidate("Open Raven", "https://www.openraven.com/", "DSPM", "catalog"),
    CompetitorCandidate("Proofpoint DSPM", "https://www.proofpoint.com/us/products/data-security-posture-management", "DSPM", "catalog"),
    CompetitorCandidate("Netskope", "https://www.netskope.com/", "Cloud Security", "catalog"),
    CompetitorCandidate("Tenable", "https://www.tenable.com/", "Exposure Management", "catalog"),
    CompetitorCandidate("Imperva", "https://www.imperva.com/", "Data Security", "catalog"),
)

DISCOVERY_NEWS_QUERIES: tuple[str, ...] = (
    '"data security posture management" vendors',
    "DSPM vendors",
    '"Concentric AI" alternatives DSPM',
    '"cloud data security" competitors',
)

NON_COMPETITOR_DOMAINS: set[str] = {
    "concentric.ai",
    "www.concentric.ai",
    "news.google.com",
    "google.com",
    "www.google.com",
    "g2.com",
    "www.g2.com",
    "gartner.com",
    "www.gartner.com",
    "reddit.com",
    "www.reddit.com",
    "cbinsights.com",
    "www.cbinsights.com",
    "techcrunch.com",
    "www.techcrunch.com",
    "businesswire.com",
    "www.businesswire.com",
    "wikipedia.org",
    "www.wikipedia.org",
}


def list_competitor_catalog() -> list[CompetitorCandidate]:
    return list(COMPETITOR_CATALOG)


def discover_competitor_candidates(max_count: int = 40, include_news: bool = False) -> list[CompetitorCandidate]:
    by_domain: dict[str, CompetitorCandidate] = {}

    for candidate in COMPETITOR_CATALOG:
        domain = extract_domain(normalize_url(candidate.url)).removeprefix("www.")
        by_domain[domain] = candidate
        if len(by_domain) >= max_count:
            break

    if include_news and len(by_domain) < max_count:
        for query in DISCOVERY_NEWS_QUERIES:
            feed_url = _news_search_feed_url(query=query)
            try:
                items = fetch_news_feed(feed_url=feed_url)
            except Exception:
                continue
            for item in items:
                normalized = normalize_url(item.article_url)
                domain = extract_domain(normalized).removeprefix("www.")
                if _skip_domain(domain):
                    continue
                if domain not in by_domain:
                    by_domain[domain] = CompetitorCandidate(
                        company_name=domain.split(".")[0].replace("-", " ").title(),
                        url=f"https://{domain}/",
                        segment="Discovered",
                        source="news_discovery",
                    )
                if len(by_domain) >= max_count:
                    break
            if len(by_domain) >= max_count:
                break

    return list(by_domain.values())[:max_count]


def _news_search_feed_url(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"


def _skip_domain(domain: str) -> bool:
    if not domain:
        return True
    lowered = domain.lower()
    if lowered in NON_COMPETITOR_DOMAINS:
        return True
    if lowered.endswith(".gov") or lowered.endswith(".edu"):
        return True
    noisy_markers = ("news", "blog", "media", "press", "journal", "insights")
    if any(marker in lowered for marker in noisy_markers):
        return True
    return False
