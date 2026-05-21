from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import quote_plus, urlparse, urlunparse
from xml.etree import ElementTree

import httpx

MAX_SUMMARY_CHARS = 900
MAX_NEWS_ITEMS = 12

TOOL_KEYWORDS: dict[str, tuple[str, str]] = {
    "aws": ("AWS", "Cloud Infrastructure"),
    "amazon web services": ("AWS", "Cloud Infrastructure"),
    "azure": ("Azure", "Cloud Infrastructure"),
    "gcp": ("Google Cloud", "Cloud Infrastructure"),
    "google cloud": ("Google Cloud", "Cloud Infrastructure"),
    "snowflake": ("Snowflake", "Data Infrastructure"),
    "databricks": ("Databricks", "Data Infrastructure"),
    "datadog": ("Datadog", "Observability"),
    "okta": ("Okta", "Identity"),
    "slack": ("Slack", "Collaboration"),
    "kubernetes": ("Kubernetes", "Platform"),
    "docker": ("Docker", "Platform"),
    "github": ("GitHub", "Developer Platform"),
    "gitlab": ("GitLab", "Developer Platform"),
    "jira": ("Jira", "Work Management"),
    "atlassian": ("Atlassian", "Work Management"),
    "servicenow": ("ServiceNow", "Operations"),
    "splunk": ("Splunk", "Security Analytics"),
    "tableau": ("Tableau", "Analytics"),
    "power bi": ("Power BI", "Analytics"),
    "looker": ("Looker", "Analytics"),
    "salesforce": ("Salesforce", "CRM"),
    "oracle": ("Oracle", "Database"),
    "mongodb": ("MongoDB", "Database"),
    "postgresql": ("PostgreSQL", "Database"),
    "kafka": ("Kafka", "Data Streaming"),
    "openai": ("OpenAI", "AI Provider"),
    "anthropic": ("Anthropic", "AI Provider"),
    "hugging face": ("Hugging Face", "AI Platform"),
}

FEATURE_PATTERNS: list[tuple[str, str, str]] = [
    (r"\bdata security posture management\b|\bdspm\b", "Data Security Posture Management", "Security"),
    (r"\bdata discovery\b|\bdiscover sensitive data\b", "Sensitive Data Discovery", "Discovery"),
    (r"\bdata classification\b|\bclassify data\b", "Data Classification", "Discovery"),
    (r"\bdata loss prevention\b|\bdlp\b", "Data Loss Prevention", "Prevention"),
    (r"\brisk prioritization\b|\brisk scoring\b", "Risk Prioritization", "Risk"),
    (r"\binsider risk\b", "Insider Risk Detection", "Risk"),
    (r"\baccess governance\b|\baccess control\b", "Access Governance", "Governance"),
    (r"\bpolicy automation\b|\bautomated policy\b", "Policy Automation", "Governance"),
    (r"\bcloud security\b|\bcloud posture\b", "Cloud Security", "Cloud"),
    (r"\bsaas security\b|\bsaas posture\b", "SaaS Security", "Cloud"),
    (r"\bthreat detection\b|\banomaly detection\b", "Threat Detection", "Detection"),
    (r"\bprompt injection\b|\bindirect prompt injection\b", "Prompt Injection Defense", "AI Security"),
    (r"\bmodel security\b|\bllm security\b", "LLM Security Controls", "AI Security"),
    (r"\bagent security\b|\bai agent security\b", "AI Agent Runtime Security", "AI Security"),
    (r"\bcompliance\b|\bregulatory\b", "Compliance Reporting", "Compliance"),
    (r"\bdata governance\b", "Data Governance", "Governance"),
]

ORG_TYPES = {
    "organization",
    "corporation",
    "localbusiness",
    "company",
    "softwareapplication",
    "webpage",
    "website",
}

ARTICLE_TYPES = {"article", "newsarticle", "blogposting", "report"}

ARTICLE_COMPANY_VERBS = {
    "acquires",
    "adds",
    "announces",
    "builds",
    "debuts",
    "expands",
    "introduces",
    "launches",
    "partners",
    "protects",
    "raises",
    "releases",
    "secures",
    "unveils",
    "uses",
}

HEADLINE_STOPWORDS = {
    "a",
    "after",
    "an",
    "as",
    "how",
    "inside",
    "the",
    "this",
    "these",
    "what",
    "when",
    "where",
    "why",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def normalize_url(raw_url: str) -> str:
    url = raw_url.strip()
    if not url:
        return url
    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
        url = f"https://{url}"
    return url


def extract_domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower()


def normalize_company_key(company_name: str) -> str:
    lowered = company_name.lower()
    lowered = re.sub(r"\b(inc|llc|corp|corporation|company|ltd|limited|technologies)\b", "", lowered)
    lowered = re.sub(r"[^a-z0-9]+", "", lowered)
    return lowered


def _candidate_urls(url: str) -> list[str]:
    candidates: list[str] = [url]
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        apex_host = host[4:]
        if apex_host:
            apex_url = urlunparse(
                (
                    parsed.scheme or "https",
                    apex_host,
                    parsed.path,
                    parsed.params,
                    parsed.query,
                    parsed.fragment,
                )
            )
            if apex_url not in candidates:
                candidates.append(apex_url)
    return candidates


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _host_to_company(host: str) -> str:
    host = host.lower().split(":")[0]
    host = host.removeprefix("www.")
    part = host.split(".")[0]
    return part.replace("-", " ").title()


def infer_company_name_from_domain(domain: str) -> str:
    return _host_to_company(domain)


def _title_to_company(title: str) -> str | None:
    if "| linkedin" in title.lower():
        first = _clean_text(title.split("|")[0])
        return first or None
    parts = re.split(r"\s[\|\-–—]\s", title)
    if not parts:
        return None
    candidate = _clean_text(parts[-1] if len(parts) > 1 else parts[0])
    if len(candidate) < 2:
        return None
    return candidate


def _headline_to_company(title: str, publisher: str | None, domain: str) -> str | None:
    headline = re.split(r"\s[\|\-–—]\s", title, maxsplit=1)[0]
    headline = _clean_text(headline)
    if not headline:
        return None

    verb_pattern = "|".join(sorted(ARTICLE_COMPANY_VERBS))
    match = re.match(
        rf"^([A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*){{0,3}})\s+({verb_pattern})\b",
        headline,
    )
    if not match:
        match = re.match(
            r"^([A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*){0,2})\s+(?:is|has|will|can)\b",
            headline,
        )
    if not match:
        return None

    candidate = _clean_text(match.group(1))
    if not candidate:
        return None
    if candidate.lower() in HEADLINE_STOPWORDS:
        return None
    if publisher and normalize_company_key(candidate) == normalize_company_key(publisher):
        return None
    if normalize_company_key(candidate) == normalize_company_key(_host_to_company(domain)):
        return None
    return candidate


def extract_linkedin_slug(url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if "linkedin.com" not in host:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] in {"company", "showcase"}:
        return re.sub(r"[^a-z0-9\-]+", "", parts[1].lower()) or None
    return None


def extract_linkedin_company_url(url: str) -> str | None:
    slug = extract_linkedin_slug(url)
    if not slug:
        return None
    return f"https://www.linkedin.com/company/{slug}/"


def derive_linkedin_company_url(company_name: str) -> str | None:
    slug = re.sub(r"[^a-z0-9]+", "-", company_name.lower()).strip("-")
    if not slug:
        return None
    return f"https://www.linkedin.com/company/{slug}/"


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self._capture_tag: str | None = None
        self.title: str = ""
        self.meta_map: dict[str, str] = {}
        self.headings: list[str] = []
        self.content_blocks: list[str] = []
        self.ld_json_blocks: list[str] = []
        self._capture_jsonld = False
        self._jsonld_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key.lower(): (value or "") for key, value in attrs}

        if tag == "title":
            self._in_title = True
            return

        if tag in {"h1", "h2", "h3", "p", "li"}:
            self._capture_tag = tag
            return

        if tag == "meta":
            key = attrs_map.get("property") or attrs_map.get("name")
            if key:
                self.meta_map[key.lower()] = _clean_text(attrs_map.get("content", ""))
            return

        if tag == "script":
            script_type = attrs_map.get("type", "").lower()
            if "ld+json" in script_type:
                self._capture_jsonld = True
                self._jsonld_buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if self._capture_tag == tag:
            self._capture_tag = None
        if tag == "script" and self._capture_jsonld:
            self._capture_jsonld = False
            joined = _clean_text(" ".join(self._jsonld_buffer))
            if joined:
                self.ld_json_blocks.append(joined)
            self._jsonld_buffer = []

    def handle_data(self, data: str) -> None:
        text = _clean_text(data)
        if not text:
            return

        if self._capture_jsonld:
            self._jsonld_buffer.append(data)
            return

        if self._in_title and not self.title:
            self.title = text
            return

        if self._capture_tag in {"h1", "h2", "h3"}:
            if len(self.headings) < 14:
                self.headings.append(text)
            return

        if self._capture_tag in {"p", "li"}:
            if len(self.content_blocks) < 80:
                self.content_blocks.append(text)


@dataclass(slots=True)
class FeatureHit:
    name: str
    category: str


@dataclass(slots=True)
class ToolHit:
    name: str
    category: str


@dataclass(slots=True)
class ScrapeResult:
    http_status: int
    final_url: str
    source_type: str
    page_title: str | None
    meta_description: str | None
    headings: list[str]
    summary: str | None
    company_name: str
    publisher: str | None
    published_at: datetime | None
    detected_features: list[FeatureHit]
    detected_tools: list[ToolHit]
    confidence: float


@dataclass(slots=True)
class NewsItem:
    title: str
    article_url: str
    publisher: str | None
    published_at: datetime | None
    summary: str | None


def _build_summary(content_blocks: list[str], fallback: str | None) -> str | None:
    blocks = content_blocks[:10]
    if not blocks:
        return fallback
    merged = " ".join(blocks)
    if len(merged) > MAX_SUMMARY_CHARS:
        return f"{merged[:MAX_SUMMARY_CHARS].rstrip()}..."
    return merged


def _flatten_jsonld(block: str) -> list[dict]:
    try:
        loaded = json.loads(block)
    except json.JSONDecodeError:
        return []

    nodes: list[dict] = []

    def visit(item: object) -> None:
        if isinstance(item, dict):
            nodes.append(item)
            if "@graph" in item:
                visit(item["@graph"])
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(loaded)
    return nodes


def _extract_jsonld_signals(blocks: list[str]) -> tuple[str | None, str | None, datetime | None, bool]:
    company_name: str | None = None
    publisher_name: str | None = None
    published_at: datetime | None = None
    is_article = False

    for block in blocks:
        nodes = _flatten_jsonld(block)
        for node in nodes:
            raw_type = node.get("@type")
            type_names: list[str]
            if isinstance(raw_type, list):
                type_names = [str(item).lower() for item in raw_type]
            elif raw_type is None:
                type_names = []
            else:
                type_names = [str(raw_type).lower()]

            if any(name in ORG_TYPES for name in type_names):
                name = node.get("name")
                if isinstance(name, str) and name.strip() and not company_name:
                    company_name = _clean_text(name)

            if any(name in ARTICLE_TYPES for name in type_names):
                is_article = True
                if not published_at:
                    published_at = _parse_datetime(
                        str(node.get("datePublished") or node.get("dateCreated") or "")
                    )
                publisher = node.get("publisher")
                if isinstance(publisher, dict):
                    pub_name = publisher.get("name")
                    if isinstance(pub_name, str) and pub_name.strip():
                        publisher_name = _clean_text(pub_name)
                if isinstance(publisher, str) and publisher.strip():
                    publisher_name = _clean_text(publisher)

    return company_name, publisher_name, published_at, is_article


def _classify_source_type(url: str, is_article: bool) -> str:
    domain = extract_domain(url)
    path = (urlparse(url).path or "").lower()
    if "linkedin.com" in domain and ("/company/" in path or "/showcase/" in path):
        return "linkedin"
    if is_article or any(token in path for token in ["/news", "/blog", "/press", "/article", "/post"]):
        return "news"
    if any(token in path for token in ["/docs", "/documentation", "/help", "/kb"]):
        return "docs"
    if any(token in path for token in ["/product", "/platform", "/solutions", "/features"]):
        return "product"
    return "website"


def _dedupe_feature_hits(items: list[FeatureHit]) -> list[FeatureHit]:
    seen: set[str] = set()
    result: list[FeatureHit] = []
    for item in items:
        key = item.name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _dedupe_tool_hits(items: list[ToolHit]) -> list[ToolHit]:
    seen: set[str] = set()
    result: list[ToolHit] = []
    for item in items:
        key = item.name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _extract_features(text: str) -> list[FeatureHit]:
    hits: list[FeatureHit] = []
    lowered = text.lower()
    for pattern, feature_name, category in FEATURE_PATTERNS:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            hits.append(FeatureHit(name=feature_name, category=category))
    return _dedupe_feature_hits(hits)


def _extract_tools(text: str) -> list[ToolHit]:
    lowered = text.lower()
    hits: list[ToolHit] = []
    for needle, (label, category) in TOOL_KEYWORDS.items():
        if needle in lowered:
            hits.append(ToolHit(name=label, category=category))
    return _dedupe_tool_hits(hits)


def _score_confidence(
    company_from_schema: bool,
    feature_count: int,
    tool_count: int,
    source_type: str,
    published_at: datetime | None,
) -> float:
    score = 0.35
    if company_from_schema:
        score += 0.25
    if feature_count >= 2:
        score += 0.2
    elif feature_count == 1:
        score += 0.1
    if tool_count >= 1:
        score += 0.1
    if source_type == "news":
        score += 0.05
    if published_at:
        score += 0.05
    return round(min(score, 0.99), 2)


def scrape_source_url(url: str) -> ScrapeResult:
    normalized_url = normalize_url(url)
    last_error: Exception | None = None
    response: httpx.Response | None = None

    for candidate in _candidate_urls(normalized_url):
        try:
            with httpx.Client(timeout=25.0, follow_redirects=True, headers=HEADERS) as client:
                response = client.get(candidate)
            break
        except httpx.HTTPError as exc:
            last_error = exc

    if response is None:
        if last_error is not None:
            raise last_error
        raise RuntimeError("Scrape failed before request was made")

    html = response.text if response.text else ""
    extractor = _Extractor()
    extractor.feed(html)

    meta_description = (
        extractor.meta_map.get("description")
        or extractor.meta_map.get("og:description")
        or extractor.meta_map.get("twitter:description")
        or None
    )
    published_at = _parse_datetime(
        extractor.meta_map.get("article:published_time")
        or extractor.meta_map.get("date")
        or extractor.meta_map.get("publishdate")
        or ""
    )

    company_from_schema, publisher_from_schema, schema_published_at, is_article = _extract_jsonld_signals(
        extractor.ld_json_blocks
    )
    if not published_at and schema_published_at:
        published_at = schema_published_at

    source_type = _classify_source_type(str(response.url), is_article=is_article)
    publisher = publisher_from_schema or extractor.meta_map.get("og:site_name") or None
    response_domain = extract_domain(str(response.url))

    if source_type == "news":
        article_company = _headline_to_company(
            title=extractor.title,
            publisher=publisher,
            domain=response_domain,
        )
        company_name = (
            article_company
            or (
                company_from_schema
                if company_from_schema
                and normalize_company_key(company_from_schema) != normalize_company_key(publisher or "")
                and normalize_company_key(company_from_schema) != normalize_company_key(_host_to_company(response_domain))
                else None
            )
            or _title_to_company(extractor.title)
            or _host_to_company(response_domain)
        )
    else:
        company_name = (
            company_from_schema
            or extractor.meta_map.get("og:site_name")
            or extractor.meta_map.get("application-name")
            or _title_to_company(extractor.title)
            or _host_to_company(response_domain)
        )
    company_name = _clean_text(company_name)

    summary = _build_summary(extractor.content_blocks, fallback=meta_description)
    detection_text = " ".join(
        [
            extractor.title,
            meta_description or "",
            *extractor.headings,
            *extractor.content_blocks,
        ]
    )
    features = _extract_features(detection_text)
    tools = _extract_tools(detection_text)
    confidence = _score_confidence(
        company_from_schema=company_from_schema is not None,
        feature_count=len(features),
        tool_count=len(tools),
        source_type=source_type,
        published_at=published_at,
    )

    return ScrapeResult(
        http_status=response.status_code,
        final_url=str(response.url),
        source_type=source_type,
        page_title=extractor.title or None,
        meta_description=meta_description,
        headings=extractor.headings[:14],
        summary=summary,
        company_name=company_name,
        publisher=publisher,
        published_at=published_at,
        detected_features=features[:30],
        detected_tools=tools[:30],
        confidence=confidence,
    )


def _news_feed_url(company_name: str, domain: str | None) -> str:
    terms = [company_name]
    if domain:
        terms.append(f"site:{domain}")
    query = quote_plus(" OR ".join(terms))
    return f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


def _fetch_news_feed(feed_url: str) -> list[NewsItem]:
    with httpx.Client(timeout=20.0, headers=HEADERS, follow_redirects=True) as client:
        response = client.get(feed_url)
    response.raise_for_status()

    root = ElementTree.fromstring(response.text)
    channel = root.find("channel")
    if channel is None:
        return []

    items: list[NewsItem] = []
    for item in channel.findall("item"):
        title = _clean_text(item.findtext("title") or "")
        link = _clean_text(item.findtext("link") or "")
        description = _clean_text(item.findtext("description") or "")
        pub_date = _clean_text(item.findtext("pubDate") or "")
        publisher = None
        source_tag = item.find("source")
        if source_tag is not None and source_tag.text:
            publisher = _clean_text(source_tag.text)
        published_at = None
        if pub_date:
            try:
                parsed = parsedate_to_datetime(pub_date)
                if parsed.tzinfo is None:
                    published_at = parsed.replace(tzinfo=timezone.utc)
                else:
                    published_at = parsed
            except (TypeError, ValueError):
                published_at = None

        if not title or not link:
            continue
        items.append(
            NewsItem(
                title=title,
                article_url=link,
                publisher=publisher,
                published_at=published_at,
                summary=description or None,
            )
        )
        if len(items) >= MAX_NEWS_ITEMS:
            break
    return items


def fetch_news_feed(feed_url: str) -> list[NewsItem]:
    return _fetch_news_feed(feed_url=feed_url)


def fetch_company_news(company_name: str, domain: str | None = None) -> list[NewsItem]:
    feed_url = _news_feed_url(company_name=company_name, domain=domain)
    return _fetch_news_feed(feed_url=feed_url)


def fetch_linkedin_news(company_name: str, linkedin_url: str | None = None) -> list[NewsItem]:
    slug = extract_linkedin_slug(linkedin_url or "")
    if slug:
        query = f"\"{company_name}\" OR site:linkedin.com/company/{slug}"
    else:
        query = f"\"{company_name}\" site:linkedin.com/company"
    feed_url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    return _fetch_news_feed(feed_url=feed_url)
