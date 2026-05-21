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
- Pulls external market news for each company using Google News RSS.
- Adds LinkedIn-specific market signals using LinkedIn-targeted news search and detected company profile URLs.
- Computes comparison view against `https://concentric.ai/` baseline.

## API (Core)

- `GET /competitive-urls`
- `POST /competitive-urls`
- `POST /competitive-urls/{id}/rescrape`
- `DELETE /competitive-urls/{id}`
- `GET /companies`
- `GET /companies/{id}`
- `POST /companies/{id}/refresh-news`
- `GET /comparison`

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
