# Competitive Intelligence Control Center

Generic competitive analysis workspace for tracking one or more unrelated markets. The app ingests competitor URLs,
extracts product signals, enriches company profiles with market evidence, and compares selected competitors against the
target company you choose.

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
- Supports saved analysis workspaces as peer company pools for unrelated markets.
- Computes comparison rows against either the default baseline, an ad hoc target company, or a workspace focus anchor.
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

## Analysis Workspaces And Focus Anchors

The product is no longer limited to one Concentric-only competitive set. A workspace is now a neutral market sandbox: it
groups peer companies that belong in the same analysis pool. The target/focus company is selected separately at viewing
time.

Examples:

- Workspace A: AI security market with `Lakera`, `HiddenLayer`, `Prompt Security`, and `Concentric AI`.
- Workspace B: CRM market with `Salesforce`, `HubSpot`, and `Microsoft Dynamics`.
- Workspace C: Cyber resilience market with `Rubrik`, `Cohesity`, and `Veeam`.

Each workspace stores:

- `name`: human-readable market or use-case name.
- `description`: optional notes for the market sandbox.
- `market_domain`: required for zero-input autonomous discovery, for example `Data Governance`, `CRM`, or `Cyber Resilience`.
- `company_ids`: the tracked peer companies in the sandbox.
- `target_company_id`: legacy/default focus fallback kept for existing local databases and API compatibility.

When `analysis_workspace_id` is supplied, `/briefing`, `/comparison`, and `/ai/ask` restrict results to that workspace's
company pool. Pass `focus_anchor_company_id` to decide which company is used as the baseline lens. The selected focus
anchor is always excluded from comparison rows, but it remains a normal member of the workspace pool so users can switch
the lens without editing the workspace.

Example:

```bash
curl "http://127.0.0.1:8000/comparison?analysis_workspace_id=3&focus_anchor_company_id=12"
```

The old default still exists as a fallback: if no workspace, focus anchor, or target company is supplied, the API can
seed and use the Concentric AI baseline so existing local data keeps working.

### Zero-Input Workspace Creation

New workspace creation no longer requires company selection or seed URLs. The UI sends only:

```json
{
  "name": "Data Governance Suite",
  "market_domain": "Data Governance",
  "description": "Optional market notes"
}
```

The API creates the workspace immediately with `status=discovering_market`, records a
`workspace_landscape_discovery` job, and starts the autonomous discovery worker. The UI closes the editor and shows the
workspace briefing canvas with `Autonomous Analyst Spinning Up...` while these phases run:

1. `discovering_market`: select the first 5-7 vendor candidates for the market domain.
2. `hydrating_entities`: resolve domains, create source rows, scrape pages, and merge companies.
3. `extracting_signals`: create workspace-local feature/tool snapshots from linked sources.
4. `calculating_gaps`: choose the first discovered leader as the default focus anchor and build the initial gap matrix.
5. `ready`: normal briefing, company, source, and gap views become available.

Discovery currently uses the local curated catalog and deterministic matching. If `WORKSPACE_DISCOVERY_INLINE=1` is set,
the worker runs inline, which is useful for tests. Otherwise it runs in a background thread in the API process.

### Workspace Isolation Boundary

Workspaces now maintain their own source links and member signal snapshots:

- `analysis_workspace_companies` stores workspace-local membership status, discovery rank, feature snapshots, tool
  snapshots, source counts, and hydration timestamps.
- `analysis_workspace_sources` links source rows to the workspace that uses them.
- `GET /competitive-urls?analysis_workspace_id=:id` returns only sources linked to that workspace.
- Workspace comparison uses the workspace member snapshots first, then falls back to global company aggregates only for
  legacy/manual workspaces without linked sources.

The global `company_profiles` table is still retained as a canonical identity layer. A future deeper migration can move
news, claims, and canonical company duplicates into fully workspace-owned tables if hard multi-tenant physical isolation
is required.

### Dynamic Anchor Retargeting

Use `POST /api/v1/workspace/re-target` to update the legacy/default focus anchor for an existing workspace. New UI flows
should usually prefer `focus_anchor_company_id` on read APIs because it swaps the lens without mutating the workspace.
The endpoint accepts `workspace_id` plus either `new_target_company_id` or `domain`.

Retargeting performs these steps:

1. Resolves or creates the new target company profile.
2. Marks the workspace as `recalculating_landscape` with the message `Recalculating Landscape...`.
3. Keeps the new target inside the workspace peer pool.
4. Refreshes and recomputes the target baseline.
5. Recomputes non-target peer profiles and rebuilds the gap matrix from the new baseline.
6. Marks the workspace `ready` and records the `retarget_job_id`, `target_version`, and `recalculated_at`.

Example:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/workspace/re-target" \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": 3,
    "new_target_company_id": 12,
    "company_ids": [7, 8, 12]
  }'
```

In the example above, company `12` becomes the default focus anchor, remains in `company_ids`, and is excluded only from
comparison rows while it is selected as the focus.

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

`GET /enrichment-connectors` and the MCP `competitive_list_enrichment_connectors` tool now return:

- `target_url`: the exact public source or API/docs entry point.
- `strategic_value`: the feature, gap, compliance, marketplace, or community signal the connector is meant to uncover.
- `method`: `source_scoped_google_news` for connectors that can safely run through the existing relevance gate today, or
  `public_api_reference` / `community_api_reference` for opt-in adapters that need API-specific handling or credentials.
- `requires_api_key` and `enabled_by_default`: used to keep expensive, noisy, or permissioned sources out of automatic
  refreshes until explicitly configured.

Expanded connector coverage:

| Domain | Connector IDs | Default refresh behavior |
| --- | --- | --- |
| AI threat and vulnerability archives | `mitre_atlas`, `ai_incident_database`, `github_advisory_database_ai`, `huntr_ai_ml_vulnerabilities`, `garak_llm_vulnerability_scanner`, `github_prompt_injection_topic`, `github_jailbreak_topic` | Source-scoped public monitoring |
| Research and academic pipelines | `arxiv_cs_cr_ai_security`, `arxiv_cs_lg_machine_learning`, `arxiv_cs_ai_artificial_intelligence`, `hugging_face_papers`, `usenix_security`, `ieee_security_privacy`, `acm_ccs`, `ndss_symposium`, `neurips_workshops_ai_security` | Source-scoped public monitoring |
| Regulatory and compliance streams | `eu_ai_act_digital_strategy`, `eu_ai_office`, `iapp_ai_governance`, `ftc_ai_enforcement`, `uk_ico_ai_guidance`, `edpb_ai_privacy_guidance`, `nist_ai_rmf` | Source-scoped public monitoring |
| Developer ecosystem and supply chain | `openssf_ai_supply_chain`, `pypi_security`, `npm_security_advisories`, `github_llmops_topic`, `github_langchain_topic`, `github_vector_database_topic`, `github_mcp_topic`, `langchain_blog`, `llamaindex_blog` | Source-scoped public monitoring |
| Enterprise app marketplaces | `salesforce_appexchange`, `servicenow_store`, `sap_store`, `aws_marketplace`, `azure_marketplace`, `google_cloud_marketplace`, `microsoft_appsource`, `atlassian_marketplace`, `okta_integration_network`, `snowflake_marketplace`, `databricks_marketplace` | Source-scoped public monitoring |
| High-signal tech communities | `hacker_news_algolia`, `reddit_machinelearning`, `reddit_localllama`, `reddit_cybersecurity`, `reddit_netsec`, `lobsters_ai_security`, `discord_ai_announcements` | Opt-in/API-reference by default, except low-volume public sources can be enabled later |

Original seed connector catalog:

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
- `GET /analysis-workspaces`
- `POST /analysis-workspaces`
- `PUT /analysis-workspaces/{workspace_id}`
- `DELETE /analysis-workspaces/{workspace_id}`
- `POST /api/v1/workspace/re-target`
- `POST /analysis-workspaces/{workspace_id}/re-target`
- `GET /briefing`
- `POST /ai/ask`
- `GET /merge-reviews?status=pending`
- `POST /merge-reviews/{id}/approve`
- `POST /merge-reviews/{id}/reject`
- `GET /ingestion-jobs`
- `POST /ingestion-jobs/run-cycle`
- `GET /comparison`
- `GET /competitive-urls?analysis_workspace_id={workspace_id}`

Scoped analysis examples:

```bash
# Compare all tracked competitors against a specific target company.
curl "http://127.0.0.1:8000/comparison?baseline_company_id=12"

# Compare only companies in a saved workspace.
curl "http://127.0.0.1:8000/comparison?analysis_workspace_id=3&focus_anchor_company_id=12"

# Generate the daily briefing for one workspace.
curl "http://127.0.0.1:8000/briefing?analysis_workspace_id=3&focus_anchor_company_id=12"

# Ask the analyst layer inside one workspace.
curl -X POST "http://127.0.0.1:8000/ai/ask" \
  -H "Content-Type: application/json" \
  -d '{"question":"Which competitor has the largest gap?","analysis_workspace_id":3}'
```

## Auto-Discovery

`POST /competitors/auto-discover` uses the curated DSPM/data-security catalog and can optionally include news-driven
discovery. Auto-discovered companies are added to the global company graph; add them to the relevant workspace before
using them in a scoped briefing or comparison.

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
