# Concentric Competitive Intelligence Platform

Competitive analysis workspace for Concentric AI. The app ingests competitor URLs, extracts product signals, enriches
company profiles with market evidence, and compares competitors against the Concentric baseline.

## What It Does

- Accepts any URL: competitor site, product page, docs page, blog post, or news article.
- Scrapes page title, metadata, headings, summary text, likely company/entity, source type, publish date, feature signals,
  and tool/platform signals.
- Merges URLs into company profiles with automatic matching and merge-review fallback for uncertain entity matches.
- Creates evidence-backed claim records with confidence, source tier, corroboration count, first/last seen timestamps,
  and evidence snippets.
- Pulls market signals from Google News RSS, LinkedIn-targeted Google News RSS, and source-scoped enrichment connectors.
- Filters news and connector results for company relevance before storage and again when reading stored records.
- Discovers competitors from a curated catalog and optional news discovery.
- Computes comparison rows against the `https://concentric.ai/` baseline.
- Supports optional AI feature/tool enrichment through OpenAI or a local OpenAI-compatible model server.
- Exposes a local MCP server so Codex can inspect and refresh enrichment data directly.

## Architecture

- `backend/app/main.py`: FastAPI API, ingestion orchestration, company merge logic, relevance gates, claim refresh.
- `backend/app/scraper.py`: HTTP scraping, HTML parsing, feature/tool extraction, news RSS parsing.
- `backend/app/enrichment.py`: source-scoped connector catalog and connector-level result filtering.
- `backend/app/ai_enrichment.py`: optional AI signal extraction for features/tools/summary.
- `backend/app/mcp_server.py`: stdio MCP server for Codex enrichment workflows.
- `backend/app/discovery.py`: curated competitor catalog and optional news-driven discovery.
- `frontend/src/App.jsx`: main competitive intelligence UI.

## Ingestion Pipeline

1. `POST /competitive-urls` normalizes and stores the submitted URL.
2. The scraper fetches the page and extracts page metadata, headings, body snippets, source type, company name, features,
   tools, and confidence.
3. Optional AI signal extraction can add structured features/tools and a summary when configured.
4. The URL is resolved into an existing or new company profile.
5. Feature/tool signals are merged into the company aggregate.
6. Claims are generated or corroborated from source-level features/tools.
7. Market news and enrichment connectors are refreshed unless bulk discovery disables market refresh for speed.

If a source redirects to an existing canonical source, the duplicate row is collapsed into the existing source.

## Feature And Tool Extraction

Local extraction uses deterministic pattern matching and domain hints. It currently covers areas such as:

- DSPM, data security, sensitive data discovery, classification, DLP, data governance
- Cloud security, SaaS security, AI security controls, prompt injection defense, AI agent runtime security
- Exposure management, vulnerability management, attack surface management, cyber risk reduction
- Cyber resilience, backup/recovery, ransomware recovery
- Workflow automation, no-code builders, document generation, e-signature, contract lifecycle management, form automation
- Common infrastructure/tools such as AWS, Azure, Google Cloud, Snowflake, Databricks, GitHub, Salesforce, OpenAI,
  Anthropic, Rubrik Security Cloud, Tenable One, OpenText Data Security, Intellistack, and Formstack

Blocked or sparse pages can still receive conservative domain/URL hints. For example, Rubrik and OpenText blocked pages
can still produce baseline data-security signals from known source/domain context.

## Relevance Filtering

Market-signal relevance is enforced in several places:

- General news and LinkedIn news are checked before insertion into `company_news`.
- Existing stored news is filtered again when returned by company detail and comparison APIs.
- Connector results require company/domain identity matches and minimum connector relevance score.
- Generic identity tokens such as `ai`, `data`, `security`, `cloud`, and `software` are ignored as standalone identity
  matches to avoid false positives.
- Google News redirect URLs are not treated as direct evidence of identity because they hide the underlying article URL.

This prevents unrelated LinkedIn or Google News items from inflating a company profile.

## Enrichment Connectors

Connectors use source-scoped Google News RSS queries of the form:

```text
("<company name>" OR "<company domain>") site:<connector domain> <connector query terms>
```

Each connector is then filtered by company/domain identity and connector/source/topic relevance.

Current connector catalog:

| ID | Name | Category | Domain |
| --- | --- | --- | --- |
| `owasp_genai_security` | OWASP GenAI Security | Security Framework | `genai.owasp.org` |
| `nist_ai_security` | NIST AI Security | Security Framework | `nist.gov` |
| `cisa_ai_security` | CISA AI Security | Security Guidance | `cisa.gov` |
| `mit_technology_review_ai` | MIT Technology Review AI | AI News | `technologyreview.com` |
| `techcrunch_ai` | TechCrunch AI | AI News | `techcrunch.com` |
| `palo_alto_unit_42` | Palo Alto Unit 42 | Threat Research | `unit42.paloaltonetworks.com` |
| `google_security_blog` | Google Security Blog | Security Research | `security.googleblog.com` |
| `aws_security_blog` | AWS Security Blog | Security Research | `aws.amazon.com/blogs/security` |
| `cloudflare_blog` | Cloudflare Blog | Security Research | `blog.cloudflare.com` |
| `mandiant_threat_intelligence` | Mandiant Threat Intelligence | Threat Research | `cloud.google.com/blog/topics/threat-intelligence` |
| `dark_reading_ai_security` | Dark Reading AI Security | Security News | `darkreading.com` |
| `the_hacker_news_ai_security` | The Hacker News AI Security | Security News | `thehackernews.com` |
| `microsoft_security_blog` | Microsoft Security Blog | Security Research | `microsoft.com` |
| `github_ai_security` | GitHub AI Security Topics | Developer Signal | `github.com` |
| `snyk_ai_security` | Snyk AI Security | Developer Security | `snyk.io/blog` |
| `semgrep_ai_security` | Semgrep AI Security | Developer Security | `semgrep.dev/blog` |
| `hugging_face` | Hugging Face | AI Ecosystem | `huggingface.co` |
| `the_rundown_ai` | The Rundown AI | AI News | `therundown.ai` |
| `venturebeat_ai` | VentureBeat AI | AI News | `venturebeat.com/ai` |
| `siliconangle_ai` | SiliconANGLE AI | AI News | `siliconangle.com` |
| `product_hunt_ai` | Product Hunt AI | Launch Signal | `producthunt.com` |
| `crunchbase_ai` | Crunchbase AI | Market Data | `crunchbase.com` |

## Optional AI Signal Extraction

AI signal extraction runs after a successful scrape and before the source is stored. It returns structured JSON:

- `company_name`
- `summary`
- `features[]`: name, category, confidence, evidence
- `tools[]`: name, category, confidence, evidence
- `confidence`
- `notes`

The AI output is merged with deterministic local extraction. If AI is disabled, unavailable, or returns invalid output,
the app silently falls back to local extraction.

### OpenAI Provider

```bash
export AI_SIGNAL_EXTRACTION_ENABLED=1
export OPENAI_API_KEY=...
# optional
export OPENAI_SIGNAL_MODEL=gpt-5.4-mini
```

The default OpenAI provider uses the Responses API with structured JSON schema output.

### Local Provider Without An OpenAI Key

Run a local OpenAI-compatible server such as Ollama or LM Studio, then set:

```bash
export AI_SIGNAL_EXTRACTION_ENABLED=1
export AI_SIGNAL_PROVIDER=ollama
export AI_SIGNAL_BASE_URL=http://127.0.0.1:11434/v1
export AI_SIGNAL_MODEL=llama3.1:8b
```

Local provider names accepted by the app:

- `local`
- `openai_compatible`
- `ollama`
- `lmstudio`

The local provider calls `/chat/completions` with JSON output mode. If your local server needs a key, set
`AI_SIGNAL_API_KEY`.

## Codex MCP Enrichment Server

The repo includes a stdio MCP server for Codex. It lets Codex inspect company context and trigger enrichment refreshes
without using the frontend.

MCP server module:

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.mcp_server --db backend/data/app.db
```

Codex config example:

```toml
[mcp_servers.genai_competitive_analysis]
command = "/Users/rp/Desktop/projects/open_source/genai-competitive-analysis/backend/.venv/bin/python"
args = [
  "-m",
  "app.mcp_server",
  "--db",
  "/Users/rp/Desktop/projects/open_source/genai-competitive-analysis/backend/data/app.db"
]
env = { PYTHONPATH = "/Users/rp/Desktop/projects/open_source/genai-competitive-analysis/backend" }
```

Available MCP tools:

- `competitive_list_companies`: list tracked companies with feature/tool and market-signal counts.
- `competitive_get_company_context`: return sources, features, tools, claims, and recent news for a company.
- `competitive_refresh_company`: refresh Google/LinkedIn news and enrichment connectors for one company.
- `competitive_list_enrichment_connectors`: list configured enrichment connectors.

After changing Codex MCP config, restart Codex or start a new Codex session.

## API

Core endpoints:

- `GET /competitive-urls`
- `POST /competitive-urls`
- `POST /competitive-urls/{id}/rescrape`
- `DELETE /competitive-urls/{id}`
- `GET /enrichment-connectors`
- `GET /decision-policy`
- `GET /competitors/catalog`
- `POST /competitors/auto-discover`
- `GET /companies`
- `GET /companies/{id}`
- `GET /companies/{id}/claims`
- `POST /companies/{id}/refresh-news`
- `POST /companies/{id}/refresh-enrichment`
- `GET /merge-reviews?status=pending`
- `POST /merge-reviews/{id}/approve`
- `POST /merge-reviews/{id}/reject`
- `GET /ingestion-jobs`
- `POST /ingestion-jobs/run-cycle`
- `GET /comparison`

## Auto-Discovery

`POST /competitors/auto-discover` uses the curated DSPM/data-security catalog and can optionally include news-driven
discovery.

Defaults:

- `include_news=true`
- `refresh_market_signals=false`

This keeps bulk discovery fast. Run `POST /ingestion-jobs/run-cycle` afterward for deeper news and enrichment refresh
across newly discovered companies.

## Scheduler

The backend can run a periodic refresh loop.

Environment variables:

- `SCHEDULE_ENABLED` defaults to `1`
- `SCHEDULE_INTERVAL_SECONDS` defaults to `1800`

Disable scheduled refreshes locally with:

```bash
export SCHEDULE_ENABLED=0
```

## Run Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Run Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend defaults to `http://127.0.0.1:8000` for the API. To point it elsewhere:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8001 npm run dev
```

## Tests

```bash
cd backend
PYTHONPATH=. pytest
```

Current backend coverage includes API permissions, workflow ingestion, connector filtering, scraper signal extraction,
AI enrichment parsing/merge behavior, scoring, company-name extraction, and the MCP server.

## Data Notes

- Default SQLite DB: `backend/data/app.db`
- Test SQLite DB: `backend/tests/test.db`
- SQLite WAL/SHM files may appear during local runs.
- Existing stored news can be pruned by running a company news/enrichment refresh; read APIs also filter irrelevant stored
  news before returning it.
