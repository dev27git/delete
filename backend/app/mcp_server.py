from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from typing import Any


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "genai-competitive-analysis"
SERVER_VERSION = "0.1.0"


def _configure_database_url() -> None:
    parser = argparse.ArgumentParser(description="MCP server for competitive enrichment")
    parser.add_argument("--database-url", default=None, help="SQLAlchemy database URL")
    parser.add_argument("--db", default=None, help="SQLite database file path")
    args = parser.parse_args()

    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url
    elif args.db:
        os.environ["DATABASE_URL"] = f"sqlite:///{args.db}"


def _json_default(value: Any) -> str:
    return str(value)


def _read_message() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            break
        key, _, value = line.decode("utf-8").partition(":")
        headers[key.lower()] = value.strip()

    content_length = int(headers.get("content-length", "0"))
    if content_length <= 0:
        return None
    raw = sys.stdin.buffer.read(content_length)
    return json.loads(raw.decode("utf-8"))


def _write_message(payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=True, default=_json_default).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


def _result(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _tool_response(payload: Any, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, indent=2, ensure_ascii=True, default=_json_default),
            }
        ],
        "isError": is_error,
    }


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "competitive_list_companies",
            "description": "List tracked competitor companies with feature/tool and market-signal counts.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum companies to return.",
                        "default": 25,
                    }
                },
            },
        },
        {
            "name": "competitive_get_company_context",
            "description": "Return sources, features, tools, claims, and recent news for one company.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "company_id": {"type": "integer"},
                    "company_name": {"type": "string"},
                    "news_limit": {"type": "integer", "default": 10},
                },
            },
        },
        {
            "name": "competitive_refresh_company",
            "description": "Refresh Google/LinkedIn news and enrichment connectors for one company.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "company_id": {"type": "integer"},
                    "company_name": {"type": "string"},
                    "refresh_news": {"type": "boolean", "default": True},
                    "refresh_enrichment": {"type": "boolean", "default": True},
                },
            },
        },
        {
            "name": "competitive_list_enrichment_connectors",
            "description": "List configured enrichment connectors and their source domains.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
        },
    ]


def _find_company(db: Any, company_id: int | None, company_name: str | None) -> Any:
    from sqlalchemy import select

    from .models import CompanyProfile

    if company_id is not None:
        company = db.get(CompanyProfile, company_id)
        if company is not None:
            return company
    if company_name:
        lowered = company_name.strip().lower()
        companies = db.scalars(select(CompanyProfile)).all()
        for company in companies:
            if company.company_name.lower() == lowered:
                return company
        for company in companies:
            if lowered in company.company_name.lower():
                return company
    raise ValueError("Company not found")


def _company_summary_payload(company: Any) -> dict[str, Any]:
    return {
        "id": company.id,
        "company_name": company.company_name,
        "primary_domain": company.primary_domain,
        "website_url": company.website_url,
        "source_count": company.source_count,
        "news_count": company.news_count,
        "last_refreshed_at": company.last_refreshed_at,
    }


def _call_list_companies(arguments: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from .database import SessionLocal
    from .main import _load_features, _load_tools
    from .models import CompanyProfile

    limit = int(arguments.get("limit") or 25)
    with SessionLocal() as db:
        companies = db.scalars(
            select(CompanyProfile)
            .options(selectinload(CompanyProfile.sources), selectinload(CompanyProfile.news_items))
            .order_by(CompanyProfile.source_count.desc(), CompanyProfile.company_name.asc())
            .limit(max(min(limit, 100), 1))
        ).all()
        return _tool_response(
            [
                {
                    **_company_summary_payload(company),
                    "features": [item.model_dump() for item in _load_features(company.feature_set_json)],
                    "tools": [item.model_dump() for item in _load_tools(company.tool_set_json)],
                }
                for company in companies
            ]
        )


def _call_get_company_context(arguments: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy.orm import selectinload

    from .database import SessionLocal
    from .main import _load_features, _load_headings, _load_tools
    from .models import CompanyProfile

    news_limit = int(arguments.get("news_limit") or 10)
    with SessionLocal() as db:
        company = _find_company(
            db=db,
            company_id=arguments.get("company_id"),
            company_name=arguments.get("company_name"),
        )
        company = db.get(
            CompanyProfile,
            company.id,
            options=[
                selectinload(CompanyProfile.sources),
                selectinload(CompanyProfile.news_items),
                selectinload(CompanyProfile.claims),
            ],
        )
        return _tool_response(
            {
                **_company_summary_payload(company),
                "features": [item.model_dump() for item in _load_features(company.feature_set_json)],
                "tools": [item.model_dump() for item in _load_tools(company.tool_set_json)],
                "sources": [
                    {
                        "url": source.source_url,
                        "domain": source.source_domain,
                        "source_type": source.source_type,
                        "title": source.page_title,
                        "summary": source.summary,
                        "headings": _load_headings(source.headings_json),
                        "features": [
                            item.model_dump() for item in _load_features(source.extracted_features_json)
                        ],
                        "tools": [item.model_dump() for item in _load_tools(source.extracted_tools_json)],
                        "confidence": source.confidence,
                        "last_error": source.last_error,
                    }
                    for source in sorted(company.sources, key=lambda item: item.updated_at, reverse=True)
                ],
                "claims": [
                    {
                        "type": claim.claim_type,
                        "value": claim.claim_value,
                        "category": claim.category,
                        "confidence": claim.confidence,
                        "source_url": claim.source_url,
                        "evidence": claim.evidence_snippet,
                    }
                    for claim in sorted(company.claims, key=lambda item: item.confidence, reverse=True)
                ],
                "recent_news": [
                    {
                        "title": item.title,
                        "url": item.article_url,
                        "source": item.source,
                        "publisher": item.publisher,
                        "published_at": item.published_at,
                    }
                    for item in sorted(
                        company.news_items,
                        key=lambda item: item.published_at or item.created_at,
                        reverse=True,
                    )[: max(min(news_limit, 50), 0)]
                ],
            }
        )


def _call_refresh_company(arguments: dict[str, Any]) -> dict[str, Any]:
    from .database import SessionLocal
    from .main import _run_company_refresh_job

    with SessionLocal() as db:
        company = _find_company(
            db=db,
            company_id=arguments.get("company_id"),
            company_name=arguments.get("company_name"),
        )
        _run_company_refresh_job(
            db=db,
            company=company,
            run_mode="mcp",
            refresh_news=bool(arguments.get("refresh_news", True)),
            refresh_enrichment=bool(arguments.get("refresh_enrichment", True)),
        )
        db.commit()
        db.refresh(company)
        return _tool_response(_company_summary_payload(company))


def _call_list_enrichment_connectors(arguments: dict[str, Any]) -> dict[str, Any]:
    del arguments
    from .enrichment import list_enrichment_connectors

    return _tool_response(
        [
            {
                "id": connector.id,
                "name": connector.name,
                "category": connector.category,
                "method": connector.method,
                "site_domain": connector.site_domain,
                "requires_api_key": connector.requires_api_key,
                "enabled_by_default": connector.enabled_by_default,
            }
            for connector in list_enrichment_connectors()
        ]
    )


def _tools() -> dict[str, Callable[[dict[str, Any]], dict[str, Any]]]:
    return {
        "competitive_list_companies": _call_list_companies,
        "competitive_get_company_context": _call_get_company_context,
        "competitive_refresh_company": _call_refresh_company,
        "competitive_list_enrichment_connectors": _call_list_enrichment_connectors,
    }


def _handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    message_id = message.get("id")
    method = message.get("method")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}

    if message_id is None:
        return None
    if method == "initialize":
        return _result(
            message_id,
            {
                "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method == "ping":
        return _result(message_id, {})
    if method == "tools/list":
        return _result(message_id, {"tools": _tool_definitions()})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        tool = _tools().get(name)
        if tool is None:
            return _error(message_id, -32601, f"Unknown tool: {name}")
        try:
            return _result(message_id, tool(arguments))
        except Exception as exc:
            return _result(message_id, _tool_response({"error": str(exc)}, is_error=True))
    if method == "resources/list":
        return _result(message_id, {"resources": []})
    if method == "prompts/list":
        return _result(message_id, {"prompts": []})
    return _error(message_id, -32601, f"Unknown method: {method}")


def main() -> None:
    _configure_database_url()
    while True:
        message = _read_message()
        if message is None:
            break
        response = _handle_request(message)
        if response is not None:
            _write_message(response)


if __name__ == "__main__":
    main()
