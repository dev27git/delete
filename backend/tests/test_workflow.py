from app.scraper import FeatureHit, NewsItem, ScrapeResult, ToolHit


def test_entity_merge_news_and_comparison(client, monkeypatch) -> None:
    scrape_responses = [
        ScrapeResult(
            http_status=200,
            final_url="https://www.lakera.ai/",
            source_type="website",
            page_title="Lakera Platform",
            meta_description="Lakera security platform",
            headings=["AI Security", "Product"],
            summary="Lakera summary",
            company_name="Lakera",
            publisher="Lakera",
            published_at=None,
            detected_features=[
                FeatureHit(name="AI Agent Runtime Security", category="AI Security"),
                FeatureHit(name="Prompt Injection Defense", category="AI Security"),
            ],
            detected_tools=[ToolHit(name="AWS", category="Cloud Infrastructure")],
            confidence=0.84,
        ),
        ScrapeResult(
            http_status=200,
            final_url="https://news.site.com/lakera-funding",
            source_type="news",
            page_title="Lakera raises funding",
            meta_description="Funding update",
            headings=["Funding", "Security"],
            summary="News summary",
            company_name="Lakera",
            publisher="NewsSite",
            published_at=None,
            detected_features=[FeatureHit(name="Threat Detection", category="Detection")],
            detected_tools=[ToolHit(name="Datadog", category="Observability")],
            confidence=0.76,
        ),
        ScrapeResult(
            http_status=200,
            final_url="https://concentric.ai/",
            source_type="website",
            page_title="Concentric AI",
            meta_description="Concentric homepage",
            headings=["Data Security Posture Management"],
            summary="Concentric summary",
            company_name="Concentric AI",
            publisher="Concentric AI",
            published_at=None,
            detected_features=[FeatureHit(name="Sensitive Data Discovery", category="Discovery")],
            detected_tools=[ToolHit(name="AWS", category="Cloud Infrastructure")],
            confidence=0.88,
        ),
    ]

    def fake_scrape(_: str) -> ScrapeResult:
        return scrape_responses.pop(0)

    def fake_news(company_name: str, domain: str | None = None) -> list[NewsItem]:
        return [
            NewsItem(
                title=f"{company_name} in the news",
                article_url=f"https://news.example.com/{company_name.lower().replace(' ', '-')}",
                publisher="Example News",
                published_at=None,
                summary="News item",
            )
        ]

    def fake_linkedin_news(company_name: str, linkedin_url: str | None = None) -> list[NewsItem]:
        return [
            NewsItem(
                title=f"{company_name} on LinkedIn",
                article_url=f"https://news.example.com/{company_name.lower().replace(' ', '-')}-linkedin",
                publisher="LinkedIn",
                published_at=None,
                summary=f"LinkedIn signal from {linkedin_url or 'derived profile'}",
            )
        ]

    monkeypatch.setattr("app.main.scrape_source_url", fake_scrape)
    monkeypatch.setattr("app.main.fetch_company_news", fake_news)
    monkeypatch.setattr("app.main.fetch_linkedin_news", fake_linkedin_news)

    add_company_page = client.post("/competitive-urls", json={"url": "https://lakera.ai"})
    assert add_company_page.status_code == 201

    add_news_page = client.post("/competitive-urls", json={"url": "https://news.site.com/lakera-funding"})
    assert add_news_page.status_code == 201
    assert add_news_page.json()["company_name"] == "Lakera"

    companies = client.get("/companies")
    assert companies.status_code == 200
    company_rows = companies.json()
    lakera = next(row for row in company_rows if row["company_name"] == "Lakera")
    assert lakera["source_count"] == 2
    assert len(lakera["features"]) >= 2
    assert len(lakera["tools"]) >= 2
    assert lakera["linkedin_url"]
    assert lakera["linkedin_news_count"] >= 1

    detail = client.get(f"/companies/{lakera['id']}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["news_count"] >= 1
    assert detail_payload["sources"][0]["company_name"] == "Lakera"

    comparison = client.get("/comparison")
    assert comparison.status_code == 200
    comparison_payload = comparison.json()
    assert comparison_payload["baseline_company_name"] == "Concentric AI"
    lakera_row = next(row for row in comparison_payload["competitors"] if row["company_name"] == "Lakera")
    assert lakera_row["linkedin_url"]
