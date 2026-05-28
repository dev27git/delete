from app.discovery import CompetitorCandidate
from app.scraper import FeatureHit, NewsItem, ScrapeResult, ToolHit


def test_zero_input_workspace_autonomous_discovery(client, monkeypatch) -> None:
    candidates = [
        CompetitorCandidate("Collibra", "https://www.collibra.com/", "Data Governance", "catalog"),
        CompetitorCandidate("Alation", "https://www.alation.com/", "Data Governance", "catalog"),
        CompetitorCandidate("Atlan", "https://atlan.com/", "Data Governance", "catalog"),
    ]

    def fake_landscape(market_domain: str, max_count: int = 7, include_news: bool = False) -> list[CompetitorCandidate]:
        assert market_domain == "Data Governance"
        return candidates[:max_count]

    scrape_by_url = {
        "https://www.collibra.com/": ScrapeResult(
            http_status=200,
            final_url="https://www.collibra.com/",
            source_type="website",
            page_title="Collibra Data Intelligence",
            meta_description="Data governance platform",
            headings=["Data Governance", "Catalog"],
            summary="Collibra data governance summary",
            company_name="Collibra",
            publisher="Collibra",
            published_at=None,
            detected_features=[FeatureHit(name="Data Catalog", category="Data Governance")],
            detected_tools=[ToolHit(name="Snowflake", category="Data Platform")],
            confidence=0.9,
        ),
        "https://www.alation.com/": ScrapeResult(
            http_status=200,
            final_url="https://www.alation.com/",
            source_type="website",
            page_title="Alation Data Catalog",
            meta_description="Data intelligence and catalog",
            headings=["Governance", "Lineage"],
            summary="Alation data catalog summary",
            company_name="Alation",
            publisher="Alation",
            published_at=None,
            detected_features=[FeatureHit(name="Data Lineage", category="Data Governance")],
            detected_tools=[ToolHit(name="Databricks", category="Data Platform")],
            confidence=0.88,
        ),
        "https://atlan.com/": ScrapeResult(
            http_status=200,
            final_url="https://atlan.com/",
            source_type="website",
            page_title="Atlan Active Metadata",
            meta_description="Active metadata platform",
            headings=["Metadata", "Governance"],
            summary="Atlan metadata summary",
            company_name="Atlan",
            publisher="Atlan",
            published_at=None,
            detected_features=[FeatureHit(name="Active Metadata", category="Data Governance")],
            detected_tools=[ToolHit(name="Google Cloud", category="Cloud Infrastructure")],
            confidence=0.86,
        ),
    }

    monkeypatch.setattr("app.main.discover_market_landscape_candidates", fake_landscape)
    monkeypatch.setattr("app.main.scrape_source_url", lambda url: scrape_by_url[url])

    workspace = client.post(
        "/analysis-workspaces",
        json={
            "name": "Data Governance Suite",
            "market_domain": "Data Governance",
            "description": "Hands-free workspace creation",
        },
    )
    assert workspace.status_code == 201, workspace.text
    workspace_payload = workspace.json()
    assert workspace_payload["status"] == "ready"
    assert workspace_payload["market_domain"] == "Data Governance"
    assert workspace_payload["company_count"] == 3
    assert workspace_payload["default_focus_company_id"] in workspace_payload["company_ids"]

    sources = client.get(f"/competitive-urls?analysis_workspace_id={workspace_payload['id']}")
    assert sources.status_code == 200
    assert len(sources.json()) == 3

    comparison = client.get(
        f"/comparison?analysis_workspace_id={workspace_payload['id']}"
        f"&focus_anchor_company_id={workspace_payload['default_focus_company_id']}"
    )
    assert comparison.status_code == 200
    comparison_payload = comparison.json()
    assert comparison_payload["analysis_workspace_id"] == workspace_payload["id"]
    assert comparison_payload["baseline_company_id"] == workspace_payload["default_focus_company_id"]
    assert len(comparison_payload["competitors"]) == 2


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

    add_baseline_page = client.post("/competitive-urls", json={"url": "https://concentric.ai/"})
    assert add_baseline_page.status_code == 201
    concentric_company_id = add_baseline_page.json()["company_id"]

    comparison = client.get("/comparison")
    assert comparison.status_code == 200
    comparison_payload = comparison.json()
    assert comparison_payload["baseline_company_name"] == "Concentric AI"
    assert comparison_payload["baseline_company_id"]
    lakera_row = next(row for row in comparison_payload["competitors"] if row["company_name"] == "Lakera")
    assert lakera_row["linkedin_url"]

    reverse_comparison = client.get(f"/comparison?baseline_company_id={lakera['id']}")
    assert reverse_comparison.status_code == 200
    reverse_payload = reverse_comparison.json()
    assert reverse_payload["baseline_company_id"] == lakera["id"]
    assert reverse_payload["baseline_company_name"] == "Lakera"
    assert any(row["company_name"] == "Concentric AI" for row in reverse_payload["competitors"])

    workspace = client.post(
        "/analysis-workspaces",
        json={
            "name": "Lakera AI security market",
            "description": "AI security peer group",
            "market_domain": "AI security",
            "company_ids": [lakera["id"], concentric_company_id],
        },
    )
    assert workspace.status_code == 201
    workspace_payload = workspace.json()
    assert workspace_payload["description"] == "AI security peer group"
    assert workspace_payload["market_domain"] == "AI security"
    assert workspace_payload["target_company_name"] == "Lakera"
    assert set(workspace_payload["company_ids"]) == {concentric_company_id, lakera["id"]}
    assert set(workspace_payload["competitor_company_ids"]) == {concentric_company_id, lakera["id"]}

    workspaces = client.get("/analysis-workspaces")
    assert workspaces.status_code == 200
    assert any(row["id"] == workspace_payload["id"] for row in workspaces.json())

    workspace_comparison = client.get(
        f"/comparison?analysis_workspace_id={workspace_payload['id']}&focus_anchor_company_id={lakera['id']}"
    )
    assert workspace_comparison.status_code == 200
    workspace_comparison_payload = workspace_comparison.json()
    assert workspace_comparison_payload["analysis_workspace_id"] == workspace_payload["id"]
    assert workspace_comparison_payload["baseline_company_id"] == lakera["id"]
    assert workspace_comparison_payload["focus_anchor_company_id"] == lakera["id"]
    assert [row["company_id"] for row in workspace_comparison_payload["competitors"]] == [concentric_company_id]

    swapped_workspace_comparison = client.get(
        f"/comparison?analysis_workspace_id={workspace_payload['id']}&focus_anchor_company_id={concentric_company_id}"
    )
    assert swapped_workspace_comparison.status_code == 200
    swapped_workspace_payload = swapped_workspace_comparison.json()
    assert swapped_workspace_payload["baseline_company_id"] == concentric_company_id
    assert [row["company_id"] for row in swapped_workspace_payload["competitors"]] == [lakera["id"]]

    briefing = client.get("/briefing")
    assert briefing.status_code == 200
    briefing_payload = briefing.json()
    assert briefing_payload["top_insights"]
    assert briefing_payload["recommended_actions"]
    assert any(step["id"] == "generate_briefing" for step in briefing_payload["onboarding"])
    assert briefing_payload["top_insights"][0]["evidence"]

    lakera_briefing = client.get(f"/briefing?baseline_company_id={lakera['id']}")
    assert lakera_briefing.status_code == 200
    assert lakera_briefing.json()["baseline_company_id"] == lakera["id"]

    workspace_briefing = client.get(
        f"/briefing?analysis_workspace_id={workspace_payload['id']}&focus_anchor_company_id={lakera['id']}"
    )
    assert workspace_briefing.status_code == 200
    workspace_briefing_payload = workspace_briefing.json()
    assert workspace_briefing_payload["analysis_workspace_id"] == workspace_payload["id"]
    assert workspace_briefing_payload["baseline_company_id"] == lakera["id"]
    assert workspace_briefing_payload["focus_anchor_company_id"] == lakera["id"]
    assert workspace_briefing_payload["totals"]["companies"] == 1

    ask = client.post("/ai/ask", json={"question": "Which competitor has the biggest product gap?"})
    assert ask.status_code == 200
    ask_payload = ask.json()
    assert ask_payload["answer"]
    assert ask_payload["recommended_next_step"]

    scoped_ask = client.post(
        "/ai/ask",
        json={
            "question": "Which competitor has the biggest product gap?",
            "baseline_company_id": lakera["id"],
        },
    )
    assert scoped_ask.status_code == 200
    assert scoped_ask.json()["answer"]

    workspace_ask = client.post(
        "/ai/ask",
        json={
            "question": "Which competitor has the biggest product gap?",
            "analysis_workspace_id": workspace_payload["id"],
            "focus_anchor_company_id": lakera["id"],
        },
    )
    assert workspace_ask.status_code == 200
    assert workspace_ask.json()["answer"]

    retarget = client.post(
        "/api/v1/workspace/re-target",
        json={
            "workspace_id": workspace_payload["id"],
            "new_target_company_id": concentric_company_id,
            "company_ids": [lakera["id"], concentric_company_id],
        },
    )
    assert retarget.status_code == 200, retarget.text
    retarget_payload = retarget.json()
    assert retarget_payload["target_company_id"] == concentric_company_id
    assert retarget_payload["status"] == "ready"
    assert retarget_payload["workspace"]["target_company_name"] == "Concentric AI"
    assert set(retarget_payload["workspace"]["company_ids"]) == {concentric_company_id, lakera["id"]}
    assert retarget_payload["workspace"]["retarget_job_id"] == retarget_payload["job_id"]
    assert retarget_payload["workspace"]["target_version"] > workspace_payload["target_version"]

    retargeted_comparison = client.get(
        f"/comparison?analysis_workspace_id={workspace_payload['id']}&focus_anchor_company_id={concentric_company_id}"
    )
    assert retargeted_comparison.status_code == 200
    retargeted_payload = retargeted_comparison.json()
    assert retargeted_payload["baseline_company_id"] == concentric_company_id
    assert [row["company_id"] for row in retargeted_payload["competitors"]] == [lakera["id"]]
    assert all(row["company_id"] != concentric_company_id for row in retargeted_payload["competitors"])


def test_market_signal_ingestion_filters_irrelevant_linkedin_posts(client, monkeypatch) -> None:
    def fake_scrape(_: str) -> ScrapeResult:
        return ScrapeResult(
            http_status=200,
            final_url="https://www.rubrik.com/",
            source_type="website",
            page_title="Rubrik",
            meta_description="Rubrik cyber resilience platform",
            headings=["Cyber Resilience"],
            summary="Rubrik protects enterprise data.",
            company_name="Rubrik",
            publisher="Rubrik",
            published_at=None,
            detected_features=[FeatureHit(name="Data Security Posture Management", category="Security")],
            detected_tools=[ToolHit(name="AWS", category="Cloud Infrastructure")],
            confidence=0.9,
        )

    def fake_news(company_name: str, domain: str | None = None) -> list[NewsItem]:
        return []

    def fake_linkedin_news(company_name: str, linkedin_url: str | None = None) -> list[NewsItem]:
        return [
            NewsItem(
                title=(
                    "Every time you pause to hunt for a file across your email, chat, "
                    "and cloud storage, you lose the flow that makes your best work possible. "
                    "With Zia Search in Zoho Workplace, everything is one click away."
                ),
                article_url=(
                    "https://news.google.com/rss/articles/"
                    "CBMiswFBVV95cUxPUG1ZeDFxZndfTDFSdDBUYTJmMml4aDZ4NVBwUk9OOEl2SXlZcHZG"
                ),
                publisher="LinkedIn",
                published_at=None,
                summary="Zoho Workplace product update.",
            ),
            NewsItem(
                title="Rubrik shares a cyber resilience update on LinkedIn",
                article_url="https://news.google.com/rss/articles/rubrik-linkedin-update",
                publisher="LinkedIn",
                published_at=None,
                summary="Rubrik product update.",
            ),
        ]

    def fake_enrichment_news(company_name: str, domain: str | None = None) -> dict[str, list[NewsItem]]:
        return {}

    monkeypatch.setattr("app.main.scrape_source_url", fake_scrape)
    monkeypatch.setattr("app.main.fetch_company_news", fake_news)
    monkeypatch.setattr("app.main.fetch_linkedin_news", fake_linkedin_news)
    monkeypatch.setattr("app.main.fetch_enrichment_news", fake_enrichment_news)

    add_company_page = client.post("/competitive-urls", json={"url": "https://www.rubrik.com/"})
    assert add_company_page.status_code == 201

    detail = client.get(f"/companies/{add_company_page.json()['company_id']}")
    assert detail.status_code == 200
    payload = detail.json()
    titles = [item["title"] for item in payload["news"]]

    assert titles == ["Rubrik shares a cyber resilience update on LinkedIn"]
    assert payload["news_source_counts"]["linkedin_news_rss"] == 1


def test_google_news_resolve_redirects_to_decoded_publisher_url(client, monkeypatch) -> None:
    def fake_scrape(_: str) -> ScrapeResult:
        return ScrapeResult(
            http_status=200,
            final_url="https://www.rubrik.com/",
            source_type="website",
            page_title="Rubrik",
            meta_description="Rubrik cyber resilience platform",
            headings=["Cyber Resilience"],
            summary="Rubrik protects enterprise data.",
            company_name="Rubrik",
            publisher="Rubrik",
            published_at=None,
            detected_features=[FeatureHit(name="Cyber Resilience", category="Resilience")],
            detected_tools=[],
            confidence=0.9,
        )

    google_url = "https://news.google.com/rss/articles/rubrik-update?oc=5"
    publisher_url = "https://www.rubrik.com/news/rubrik-update"

    def fake_news(company_name: str, domain: str | None = None) -> list[NewsItem]:
        return [
            NewsItem(
                title="Rubrik announces a cyber resilience update",
                article_url=google_url,
                publisher="Rubrik",
                published_at=None,
                summary="Rubrik cyber resilience update.",
            )
        ]

    monkeypatch.setattr("app.main.scrape_source_url", fake_scrape)
    monkeypatch.setattr("app.main.fetch_company_news", fake_news)
    monkeypatch.setattr("app.main.fetch_linkedin_news", lambda company_name, linkedin_url=None: [])
    monkeypatch.setattr("app.main.fetch_enrichment_news", lambda company_name, domain=None: {})
    monkeypatch.setattr("app.main.resolve_google_news_article_url", lambda article_url: publisher_url)

    add_company_page = client.post("/competitive-urls", json={"url": "https://www.rubrik.com/"})
    assert add_company_page.status_code == 201
    detail = client.get(f"/companies/{add_company_page.json()['company_id']}")
    news_id = detail.json()["news"][0]["id"]

    response = client.get(f"/news/{news_id}/resolve", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == publisher_url

    refreshed = client.get(f"/companies/{add_company_page.json()['company_id']}")
    assert refreshed.json()["news"][0]["article_url"] == publisher_url


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


def test_auto_discovery_dedupes_redirect_collisions(client, monkeypatch) -> None:
    duplicate_final_url = "https://www.intellistack.com/?utm_source=or-redirect&utm_medium=referral"

    def fake_discover(max_count: int = 40, include_news: bool = False) -> list[CompetitorCandidate]:
        return [
            CompetitorCandidate(
                company_name="Intellistack Landing A",
                url="https://www.formstack.com/redirect-a",
                segment="Discovered",
                source="test",
            ),
            CompetitorCandidate(
                company_name="Intellistack Landing B",
                url="https://www.formstack.com/redirect-b",
                segment="Discovered",
                source="test",
            ),
        ][:max_count]

    def fake_scrape(_: str) -> ScrapeResult:
        return ScrapeResult(
            http_status=200,
            final_url=duplicate_final_url,
            source_type="website",
            page_title="Intellistack Landing",
            meta_description="Intellistack AI workflows",
            headings=["Intellistack", "AI-Native No-Code Workflows"],
            summary="Intellistack summary.",
            company_name="Intellistack",
            publisher="Intellistack",
            published_at=None,
            detected_features=[],
            detected_tools=[ToolHit(name="Salesforce", category="CRM")],
            confidence=0.7,
        )

    monkeypatch.setattr("app.main.discover_competitor_candidates", fake_discover)
    monkeypatch.setattr("app.main.scrape_source_url", fake_scrape)

    response = client.post(
        "/competitors/auto-discover?max_candidates=60&include_news=false&refresh_market_signals=false"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["added_sources"] == 1
    assert payload["skipped_existing"] >= 1
    assert len(payload["urls_added"]) == 1
    assert payload["urls_added"][0] == duplicate_final_url

    sources = client.get("/competitive-urls")
    assert sources.status_code == 200
    source_rows = sources.json()
    assert len(source_rows) == 1


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


def test_workspace_auto_discovery_links_existing_and_new_sources(client, monkeypatch) -> None:
    scrape_map = {
        "https://www.cyera.com/": ScrapeResult(
            http_status=200,
            final_url="https://www.cyera.com/",
            source_type="website",
            page_title="Cyera Platform",
            meta_description="Cyera DSPM",
            headings=["DSPM"],
            summary="Cyera summary",
            company_name="Cyera",
            publisher="Cyera",
            published_at=None,
            detected_features=[FeatureHit(name="Data Security Posture Management", category="Security")],
            detected_tools=[],
            confidence=0.84,
        ),
        "https://www.sentra.io/": ScrapeResult(
            http_status=200,
            final_url="https://www.sentra.io/",
            source_type="website",
            page_title="Sentra DSPM",
            meta_description="Sentra DSPM",
            headings=["Data Security"],
            summary="Sentra summary",
            company_name="Sentra",
            publisher="Sentra",
            published_at=None,
            detected_features=[FeatureHit(name="Threat Detection", category="Detection")],
            detected_tools=[],
            confidence=0.82,
        ),
    }

    def fake_landscape(market_domain: str, max_count: int = 7, include_news: bool = False) -> list[CompetitorCandidate]:
        assert market_domain == "DSPM"
        assert include_news is False
        return [
            CompetitorCandidate(company_name="Cyera", url="https://www.cyera.com/", segment="DSPM", source="catalog"),
            CompetitorCandidate(company_name="Sentra", url="https://www.sentra.io/", segment="DSPM", source="catalog"),
        ][:max_count]

    monkeypatch.setattr("app.main.scrape_source_url", lambda url: scrape_map[url])
    monkeypatch.setattr("app.main.fetch_company_news", lambda company_name, domain=None: [])
    monkeypatch.setattr("app.main.fetch_linkedin_news", lambda company_name, linkedin_url=None: [])
    monkeypatch.setattr("app.main.fetch_enrichment_news", lambda company_name, domain=None: {})
    monkeypatch.setattr("app.main.discover_market_landscape_candidates", fake_landscape)

    cyera = client.post("/competitive-urls", json={"url": "https://www.cyera.com/"})
    assert cyera.status_code == 201
    workspace = client.post(
        "/analysis-workspaces",
        json={
            "name": "DSPM Market",
            "market_domain": "DSPM",
            "company_ids": [cyera.json()["company_id"]],
        },
    )
    assert workspace.status_code == 201

    response = client.post(
        f"/competitors/auto-discover?max_candidates=10&include_news=false&analysis_workspace_id={workspace.json()['id']}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["added_sources"] == 2
    assert payload["failed_sources"] == 0

    scoped_sources = client.get(f"/competitive-urls?analysis_workspace_id={workspace.json()['id']}")
    assert scoped_sources.status_code == 200
    assert {row["company_name"] for row in scoped_sources.json()} == {"Cyera", "Sentra"}


def test_rescrape_preserves_workspace_link_when_url_redirects_to_existing_source(client, monkeypatch) -> None:
    scrape_map = {
        "https://existing.example/": ScrapeResult(
            http_status=200,
            final_url="https://existing.example/",
            source_type="website",
            page_title="ExistingCo",
            meta_description="Existing security platform",
            headings=["Cloud Security"],
            summary="Existing summary",
            company_name="ExistingCo",
            publisher="ExistingCo",
            published_at=None,
            detected_features=[FeatureHit(name="Cloud Security", category="Cloud")],
            detected_tools=[],
            confidence=0.8,
        ),
        "https://temp.example/": ScrapeResult(
            http_status=200,
            final_url="https://temp.example/",
            source_type="website",
            page_title="TempCo",
            meta_description="Temporary platform",
            headings=["Workflow Automation"],
            summary="Temporary summary",
            company_name="TempCo",
            publisher="TempCo",
            published_at=None,
            detected_features=[FeatureHit(name="Workflow Automation", category="Automation")],
            detected_tools=[],
            confidence=0.72,
        ),
    }

    monkeypatch.setattr("app.main.scrape_source_url", lambda url: scrape_map[url])
    monkeypatch.setattr("app.main.fetch_company_news", lambda company_name, domain=None: [])
    monkeypatch.setattr("app.main.fetch_linkedin_news", lambda company_name, linkedin_url=None: [])
    monkeypatch.setattr("app.main.fetch_enrichment_news", lambda company_name, domain=None: {})

    existing = client.post("/competitive-urls", json={"url": "https://existing.example/"})
    assert existing.status_code == 201
    workspace = client.post(
        "/analysis-workspaces",
        json={
            "name": "Redirect Market",
            "market_domain": "Security",
            "company_ids": [existing.json()["company_id"]],
        },
    )
    assert workspace.status_code == 201

    temp = client.post(
        "/competitive-urls",
        json={"url": "https://temp.example/", "analysis_workspace_id": workspace.json()["id"]},
    )
    assert temp.status_code == 201

    scrape_map["https://temp.example/"] = ScrapeResult(
        http_status=200,
        final_url="https://existing.example/",
        source_type="website",
        page_title="ExistingCo",
        meta_description="Existing security platform",
        headings=["Cloud Security"],
        summary="Existing summary",
        company_name="ExistingCo",
        publisher="ExistingCo",
        published_at=None,
        detected_features=[FeatureHit(name="Cloud Security", category="Cloud")],
        detected_tools=[],
        confidence=0.84,
    )

    rescraped = client.post(f"/competitive-urls/{temp.json()['id']}/rescrape")
    assert rescraped.status_code == 200
    assert rescraped.json()["id"] == existing.json()["id"]

    scoped_sources = client.get(f"/competitive-urls?analysis_workspace_id={workspace.json()['id']}")
    assert scoped_sources.status_code == 200
    assert any(row["id"] == existing.json()["id"] for row in scoped_sources.json())
