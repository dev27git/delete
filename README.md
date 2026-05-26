# Concentric Competitive Intelligence Platform

Competitive analysis workspace for Concentric AI.

## What It Does

- Accepts **any URL** (competitor site, product page, docs page, blog, news article).
- Scrapes and extracts:
  - likely company/entity
  - feature signals
  - tool stack signals
  - summary and metadata
- Merges URLs into the same company profile when entity matches.
- Creates evidence-backed claim records with confidence, source tier, corroboration count, and first/last seen timestamps.
- Queues uncertain entity merges for analyst approval in a merge-review workflow.
- Automatically discovers competitors from a DSPM catalog and optional news-driven discovery, then ingests them in bulk.
- Pulls external market news for each company using Google News RSS.
- Adds LinkedIn-specific market signals using LinkedIn-targeted news search and detected company profile URLs.
- Enriches company profiles through source-scoped connectors for OWASP GenAI Security, MIT Technology Review AI,
  TechCrunch AI, Palo Alto Unit 42, Microsoft Security Blog, GitHub AI Security Topics, Hugging Face,
  The Rundown AI, Product Hunt AI, and Crunchbase AI.
- Computes comparison view against `https://concentric.ai/` baseline.

## API (Core)

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

### Optional Scheduler

- `SCHEDULE_ENABLED` (default: `1`)
- `SCHEDULE_INTERVAL_SECONDS` (default: `1800`)

### Auto-Discovery Notes

- `POST /competitors/auto-discover` now defaults to `include_news=true` for broader discovery.
- It also defaults to `refresh_market_signals=false` to keep bulk discovery fast and avoid long request times.
- After discovery, run `POST /ingestion-jobs/run-cycle` for deep news + enrichment refresh across newly discovered companies.

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

Frontend defaults to `http://127.0.0.1:8000` for API.

## Tests

```bash
cd backend
PYTHONPATH=. pytest
```
