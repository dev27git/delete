from __future__ import annotations

from app import enrichment
from app.enrichment import EnrichmentConnector
from app.scraper import NewsItem


def test_connector_catalog_has_unique_ids() -> None:
    connectors = enrichment.list_enrichment_connectors()
    connector_ids = [connector.id for connector in connectors]

    assert len(connectors) >= 20
    assert len(connector_ids) == len(set(connector_ids))


def test_connector_relevance_requires_company_identity() -> None:
    connector = EnrichmentConnector(
        id="techcrunch_ai",
        name="TechCrunch AI",
        category="AI News",
        method="source_scoped_google_news",
        site_domain="techcrunch.com",
        query_terms=("AI", "security"),
    )
    item = NewsItem(
        title="OpenAI launches a new enterprise security feature",
        article_url="https://techcrunch.com/openai-enterprise-security",
        publisher="TechCrunch",
        published_at=None,
        summary="The AI company is expanding security tooling for enterprise teams.",
    )

    score = enrichment._connector_item_relevance_score(
        connector=connector,
        item=item,
        company_name="Concentric AI",
        domain="concentric.ai",
    )

    assert score == 0.0


def test_connector_relevance_accepts_company_domain_mentions() -> None:
    connector = EnrichmentConnector(
        id="unit_42",
        name="Unit 42",
        category="Threat Research",
        method="source_scoped_google_news",
        site_domain="unit42.paloaltonetworks.com",
        query_terms=("AI", "security", "threat"),
    )
    item = NewsItem(
        title="Threat researchers analyze AI security controls",
        article_url="https://unit42.paloaltonetworks.com/ai-security-controls",
        publisher="Unit 42",
        published_at=None,
        summary="The report mentions lakera.ai while reviewing prompt-injection defenses.",
    )

    score = enrichment._connector_item_relevance_score(
        connector=connector,
        item=item,
        company_name="Lakera",
        domain="lakera.ai",
    )

    assert score >= enrichment.MIN_CONNECTOR_RELEVANCE_SCORE


def test_fetch_enrichment_news_filters_irrelevant_feed_items(monkeypatch) -> None:
    connector = EnrichmentConnector(
        id="techcrunch_ai",
        name="TechCrunch AI",
        category="AI News",
        method="source_scoped_google_news",
        site_domain="techcrunch.com",
        query_terms=("AI", "security"),
    )

    def fake_fetch_news_feed(feed_url: str) -> list[NewsItem]:
        return [
            NewsItem(
                title="OpenAI expands enterprise security",
                article_url="https://techcrunch.com/openai-security",
                publisher="TechCrunch",
                published_at=None,
                summary="A general AI security story without the tracked company.",
            ),
            NewsItem(
                title="Lakera launches new AI security product",
                article_url="https://techcrunch.com/lakera-ai-security",
                publisher="TechCrunch",
                published_at=None,
                summary="Lakera released controls for prompt injection protection.",
            ),
        ]

    monkeypatch.setattr(enrichment, "CONNECTORS", (connector,))
    monkeypatch.setattr(enrichment, "fetch_news_feed", fake_fetch_news_feed)

    results = enrichment.fetch_enrichment_news(company_name="Lakera", domain="lakera.ai")

    assert [item.title for item in results["techcrunch_ai"]] == [
        "Lakera launches new AI security product"
    ]
