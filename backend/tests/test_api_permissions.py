from app.scraper import FeatureHit, NewsItem, ScrapeResult, ToolHit


def _fake_scrape(url: str) -> ScrapeResult:
    return ScrapeResult(
        http_status=200,
        final_url=url,
        source_type="website",
        page_title="Competitor Product Page",
        meta_description="Data security platform overview.",
        headings=["Platform", "Capabilities"],
        summary="Automated test scrape summary.",
        company_name="Lakera",
        publisher="Lakera",
        published_at=None,
        detected_features=[
            FeatureHit(name="AI Agent Runtime Security", category="AI Security"),
            FeatureHit(name="Prompt Injection Defense", category="AI Security"),
        ],
        detected_tools=[ToolHit(name="AWS", category="Cloud Infrastructure")],
        confidence=0.83,
    )


def _fake_news(company_name: str, domain: str | None = None) -> list[NewsItem]:
    return [
        NewsItem(
            title=f"{company_name} launches new security feature",
            article_url=f"https://news.example.com/{company_name.lower().replace(' ', '-')}-launch",
            publisher="TechNews",
            published_at=None,
            summary="Launch coverage",
        )
    ]


def _fake_linkedin_news(company_name: str, linkedin_url: str | None = None) -> list[NewsItem]:
    return [
        NewsItem(
            title=f"{company_name} shared product update on LinkedIn",
            article_url=f"https://news.example.com/{company_name.lower().replace(' ', '-')}-linkedin",
            publisher="LinkedIn",
            published_at=None,
            summary=f"LinkedIn signal from {linkedin_url or 'derived profile'}",
        )
    ]


def _fake_enrichment_news(company_name: str, domain: str | None = None) -> dict[str, list[NewsItem]]:
    return {
        "techcrunch_ai": [
            NewsItem(
                title=f"{company_name} funding signal",
                article_url=f"https://techcrunch.example.com/{company_name.lower().replace(' ', '-')}",
                publisher="TechCrunch",
                published_at=None,
                summary=f"Connector signal for {domain or company_name}",
            )
        ]
    }


def test_add_competitive_url_scrapes_and_returns_payload(client, monkeypatch) -> None:
    monkeypatch.setattr("app.main.scrape_source_url", _fake_scrape)
    monkeypatch.setattr("app.main.fetch_company_news", _fake_news)
    monkeypatch.setattr("app.main.fetch_linkedin_news", _fake_linkedin_news)
    monkeypatch.setattr("app.main.fetch_enrichment_news", _fake_enrichment_news)

    response = client.post("/competitive-urls", json={"url": "https://example.com"})
    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "scraped"
    assert payload["company_name"] == "Lakera"
    assert payload["detected_tools"][0]["name"] == "AWS"
    assert payload["detected_features"][0]["name"] == "AI Agent Runtime Security"


def test_duplicate_competitive_url_is_rejected(client, monkeypatch) -> None:
    monkeypatch.setattr("app.main.scrape_source_url", _fake_scrape)
    monkeypatch.setattr("app.main.fetch_company_news", _fake_news)
    monkeypatch.setattr("app.main.fetch_linkedin_news", _fake_linkedin_news)
    monkeypatch.setattr("app.main.fetch_enrichment_news", _fake_enrichment_news)

    first = client.post("/competitive-urls", json={"url": "https://example.com"})
    assert first.status_code == 201
    second = client.post("/competitive-urls", json={"url": "https://example.com"})
    assert second.status_code == 409


def test_enrichment_connectors_are_listed(client) -> None:
    response = client.get("/enrichment-connectors")
    assert response.status_code == 200
    connector_ids = {item["id"] for item in response.json()}
    assert "techcrunch_ai" in connector_ids
    assert "owasp_genai_security" in connector_ids
