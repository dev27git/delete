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

    def fake_enrichment_news(company_name: str, domain: str | None = None) -> dict[str, list[NewsItem]]:
        return {
            "techcrunch_ai": [
                NewsItem(
                    title=f"{company_name} covered by TechCrunch",
                    article_url=f"https://techcrunch.example.com/{company_name.lower().replace(' ', '-')}",
                    publisher="TechCrunch",
                    published_at=None,
                    summary=f"Enrichment signal for {domain or company_name}",
                )
            ],
            "palo_alto_unit_42": [
                NewsItem(
                    title=f"{company_name} threat research mention",
                    article_url=f"https://unit42.example.com/{company_name.lower().replace(' ', '-')}",
                    publisher="Unit 42",
                    published_at=None,
                    summary="Threat research signal",
                )
            ],
        }

    monkeypatch.setattr("app.main.scrape_source_url", fake_scrape)
    monkeypatch.setattr("app.main.fetch_company_news", fake_news)
    monkeypatch.setattr("app.main.fetch_linkedin_news", fake_linkedin_news)
    monkeypatch.setattr("app.main.fetch_enrichment_news", fake_enrichment_news)

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
    assert lakera["enrichment_news_count"] >= 2
    assert lakera["news_source_counts"]["enrichment:techcrunch_ai"] == 1

    detail = client.get(f"/companies/{lakera['id']}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["news_count"] >= 1
    assert detail_payload["sources"][0]["company_name"] == "Lakera"
    assert any(item["source"] == "enrichment:techcrunch_ai" for item in detail_payload["news"])

    refresh_enrichment = client.post(f"/companies/{lakera['id']}/refresh-enrichment")
    assert refresh_enrichment.status_code == 200

    comparison = client.get("/comparison")
    assert comparison.status_code == 200
    comparison_payload = comparison.json()
    assert comparison_payload["baseline_company_name"] == "Concentric AI"
    lakera_row = next(row for row in comparison_payload["competitors"] if row["company_name"] == "Lakera")
    assert lakera_row["linkedin_url"]


def test_claims_and_ingestion_jobs(client, monkeypatch) -> None:
    scrape_responses = [
        ScrapeResult(
            http_status=200,
            final_url="https://www.lakera.ai/",
            source_type="product",
            page_title="Lakera Product",
            meta_description="Lakera AI security platform",
            headings=["Prompt Injection Defense", "AI Agent Runtime Security"],
            summary="Lakera product evidence summary.",
            company_name="Lakera",
            publisher="Lakera",
            published_at=None,
            detected_features=[
                FeatureHit(name="Prompt Injection Defense", category="AI Security"),
                FeatureHit(name="AI Agent Runtime Security", category="AI Security"),
            ],
            detected_tools=[ToolHit(name="AWS", category="Cloud Infrastructure")],
            confidence=0.91,
        )
    ]

    def fake_scrape(_: str) -> ScrapeResult:
        return scrape_responses.pop(0)

    def fake_news(company_name: str, domain: str | None = None) -> list[NewsItem]:
        return [
            NewsItem(
                title=f"{company_name} market signal",
                article_url=f"https://news.example.com/{company_name.lower()}-signal",
                publisher="Example News",
                published_at=None,
                summary="market signal",
            )
        ]

    def fake_linkedin_news(company_name: str, linkedin_url: str | None = None) -> list[NewsItem]:
        return [
            NewsItem(
                title=f"{company_name} linkedin signal",
                article_url=f"https://news.example.com/{company_name.lower()}-linkedin-signal",
                publisher="LinkedIn",
                published_at=None,
                summary=f"LinkedIn signal from {linkedin_url or 'derived profile'}",
            )
        ]

    def fake_enrichment_news(company_name: str, domain: str | None = None) -> dict[str, list[NewsItem]]:
        return {
            "techcrunch_ai": [
                NewsItem(
                    title=f"{company_name} techcrunch signal",
                    article_url=f"https://techcrunch.example.com/{company_name.lower()}-signal",
                    publisher="TechCrunch",
                    published_at=None,
                    summary="enrichment signal",
                )
            ]
        }

    monkeypatch.setattr("app.main.scrape_source_url", fake_scrape)
    monkeypatch.setattr("app.main.fetch_company_news", fake_news)
    monkeypatch.setattr("app.main.fetch_linkedin_news", fake_linkedin_news)
    monkeypatch.setattr("app.main.fetch_enrichment_news", fake_enrichment_news)

    add_source = client.post("/competitive-urls", json={"url": "https://lakera.ai"})
    assert add_source.status_code == 201
    company_id = add_source.json()["company_id"]
    assert company_id is not None

    claims = client.get(f"/companies/{company_id}/claims")
    assert claims.status_code == 200
    claim_payload = claims.json()
    claim_types = {item["claim_type"] for item in claim_payload}
    assert "feature" in claim_types
    assert "tool" in claim_types

    refresh_news = client.post(f"/companies/{company_id}/refresh-news")
    assert refresh_news.status_code == 200

    jobs = client.get("/ingestion-jobs?limit=20")
    assert jobs.status_code == 200
    jobs_payload = jobs.json()
    assert len(jobs_payload) >= 1
    assert jobs_payload[0]["job_type"] == "company_refresh"
    assert jobs_payload[0]["run_mode"] == "manual"


def test_merge_review_queue_and_approval(client, monkeypatch) -> None:
    scrape_responses = [
        ScrapeResult(
            http_status=200,
            final_url="https://lakera.ai/",
            source_type="website",
            page_title="Lakera Platform",
            meta_description="Lakera page",
            headings=["AI Security"],
            summary="Lakera summary",
            company_name="Lakera",
            publisher="Lakera",
            published_at=None,
            detected_features=[FeatureHit(name="Prompt Injection Defense", category="AI Security")],
            detected_tools=[ToolHit(name="AWS", category="Cloud Infrastructure")],
            confidence=0.86,
        ),
        ScrapeResult(
            http_status=200,
            final_url="https://lokera.ai/",
            source_type="website",
            page_title="Lokera Platform",
            meta_description="Lokera page",
            headings=["AI Security"],
            summary="Lokera summary",
            company_name="Lokera",
            publisher="Lokera",
            published_at=None,
            detected_features=[FeatureHit(name="Prompt Injection Defense", category="AI Security")],
            detected_tools=[ToolHit(name="AWS", category="Cloud Infrastructure")],
            confidence=0.82,
        ),
    ]

    def fake_scrape(_: str) -> ScrapeResult:
        return scrape_responses.pop(0)

    def fake_news(company_name: str, domain: str | None = None) -> list[NewsItem]:
        return []

    def fake_linkedin_news(company_name: str, linkedin_url: str | None = None) -> list[NewsItem]:
        return []

    def fake_enrichment_news(company_name: str, domain: str | None = None) -> dict[str, list[NewsItem]]:
        return {}

    monkeypatch.setattr("app.main.scrape_source_url", fake_scrape)
    monkeypatch.setattr("app.main.fetch_company_news", fake_news)
    monkeypatch.setattr("app.main.fetch_linkedin_news", fake_linkedin_news)
    monkeypatch.setattr("app.main.fetch_enrichment_news", fake_enrichment_news)

    first = client.post("/competitive-urls", json={"url": "https://lakera.ai"})
    assert first.status_code == 201
    second = client.post("/competitive-urls", json={"url": "https://lokera.ai"})
    assert second.status_code == 201

    pending = client.get("/merge-reviews?status=pending")
    assert pending.status_code == 200
    pending_items = pending.json()
    assert len(pending_items) >= 1
    review = pending_items[0]
    assert review["detected_company_name"] == "Lokera"
    assert review["candidate_company_name"] == "Lakera"

    approved = client.post(f"/merge-reviews/{review['id']}/approve", json={})
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


def test_auto_discover_competitors_endpoint(client, monkeypatch) -> None:
    calls = {"news": 0, "linkedin": 0, "enrichment": 0}
    scrape_map = {
        "https://www.cyera.com/": ScrapeResult(
            http_status=200,
            final_url="https://www.cyera.com/",
            source_type="website",
            page_title="Cyera Platform",
            meta_description="Cyera DSPM",
            headings=["DSPM", "Data Security"],
            summary="Cyera summary",
            company_name="Cyera",
            publisher="Cyera",
            published_at=None,
            detected_features=[FeatureHit(name="Data Security Posture Management", category="Security")],
            detected_tools=[ToolHit(name="AWS", category="Cloud Infrastructure")],
            confidence=0.84,
        ),
        "https://www.sentra.io/": ScrapeResult(
            http_status=200,
            final_url="https://www.sentra.io/",
            source_type="website",
            page_title="Sentra",
            meta_description="Sentra DSPM",
            headings=["DSPM", "Security"],
            summary="Sentra summary",
            company_name="Sentra",
            publisher="Sentra",
            published_at=None,
            detected_features=[FeatureHit(name="Threat Detection", category="Detection")],
            detected_tools=[ToolHit(name="Azure", category="Cloud Infrastructure")],
            confidence=0.82,
        ),
    }

    def fake_scrape(url: str) -> ScrapeResult:
        return scrape_map[url]

    def fake_news(company_name: str, domain: str | None = None) -> list[NewsItem]:
        calls["news"] += 1
        return []

    def fake_linkedin_news(company_name: str, linkedin_url: str | None = None) -> list[NewsItem]:
        calls["linkedin"] += 1
        return []

    def fake_enrichment_news(company_name: str, domain: str | None = None) -> dict[str, list[NewsItem]]:
        calls["enrichment"] += 1
        return {}

    def fake_candidates(max_count: int = 40, include_news: bool = False):
        from app.discovery import CompetitorCandidate

        return [
            CompetitorCandidate(company_name="Cyera", url="https://www.cyera.com/", segment="DSPM", source="catalog"),
            CompetitorCandidate(company_name="Sentra", url="https://www.sentra.io/", segment="DSPM", source="catalog"),
        ][:max_count]

    monkeypatch.setattr("app.main.scrape_source_url", fake_scrape)
    monkeypatch.setattr("app.main.fetch_company_news", fake_news)
    monkeypatch.setattr("app.main.fetch_linkedin_news", fake_linkedin_news)
    monkeypatch.setattr("app.main.fetch_enrichment_news", fake_enrichment_news)
    monkeypatch.setattr("app.main.discover_competitor_candidates", fake_candidates)

    response = client.post("/competitors/auto-discover?max_candidates=10&include_news=false")
    assert response.status_code == 200
    payload = response.json()
    assert payload["candidates_considered"] == 2
    assert payload["added_sources"] == 2
    assert payload["failed_sources"] == 0
    assert calls["news"] == 0
    assert calls["linkedin"] == 0
    assert calls["enrichment"] == 0

    companies = client.get("/companies")
    assert companies.status_code == 200
    names = {row["company_name"] for row in companies.json()}
    assert "Cyera" in names
    assert "Sentra" in names
