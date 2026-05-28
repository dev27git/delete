from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from .scraper import ScrapeResult

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_SIGNAL_MODEL = "gpt-5.4-mini"
DEFAULT_LOCAL_SIGNAL_MODEL = "llama3.1:8b"
DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:11434/v1"
AI_SIGNAL_CONTEXT_CHARS = 5500
AI_MIN_SIGNAL_CONFIDENCE = 0.55
LOCAL_PROVIDER_NAMES = {"local", "openai_compatible", "ollama", "lmstudio"}


@dataclass(frozen=True, slots=True)
class AISignalHit:
    name: str
    category: str
    confidence: float
    evidence: str


@dataclass(frozen=True, slots=True)
class AISignalExtraction:
    company_name: str
    summary: str
    features: list[AISignalHit]
    tools: list[AISignalHit]
    confidence: float
    notes: str


SIGNAL_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["company_name", "summary", "features", "tools", "confidence", "notes"],
    "properties": {
        "company_name": {"type": "string"},
        "summary": {"type": "string"},
        "features": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "category", "confidence", "evidence"],
                "properties": {
                    "name": {"type": "string"},
                    "category": {"type": "string"},
                    "confidence": {"type": "number"},
                    "evidence": {"type": "string"},
                },
            },
        },
        "tools": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "category", "confidence", "evidence"],
                "properties": {
                    "name": {"type": "string"},
                    "category": {"type": "string"},
                    "confidence": {"type": "number"},
                    "evidence": {"type": "string"},
                },
            },
        },
        "confidence": {"type": "number"},
        "notes": {"type": "string"},
    },
}


def ai_signal_extraction_enabled() -> bool:
    enabled = os.getenv("AI_SIGNAL_EXTRACTION_ENABLED", "0").lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return False
    if _ai_signal_provider() in LOCAL_PROVIDER_NAMES:
        return True
    return bool(os.getenv("OPENAI_API_KEY"))


def extract_ai_signals(scrape: ScrapeResult) -> AISignalExtraction | None:
    if not ai_signal_extraction_enabled():
        return None

    try:
        payload = _request_signal_extraction(scrape=scrape)
        return _parse_signal_extraction(payload)
    except Exception:
        return None


def _request_signal_extraction(scrape: ScrapeResult) -> dict[str, Any]:
    if _ai_signal_provider() in LOCAL_PROVIDER_NAMES:
        return _request_local_signal_extraction(scrape=scrape)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for AI signal extraction")

    request_payload = {
        "model": os.getenv("OPENAI_SIGNAL_MODEL", DEFAULT_OPENAI_SIGNAL_MODEL),
        "input": [
            {
                "role": "system",
                "content": (
                    "You extract competitive-intelligence signals from scraped web page evidence. "
                    "Return only signals supported by the provided text. Do not infer capabilities "
                    "from brand reputation. Use concise product capability names."
                ),
            },
            {
                "role": "user",
                "content": _build_signal_prompt(scrape=scrape),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "competitive_signals",
                "strict": True,
                "schema": SIGNAL_EXTRACTION_SCHEMA,
            }
        },
    }

    base_url = os.getenv("OPENAI_BASE_URL", OPENAI_RESPONSES_URL).rstrip("/")
    responses_url = base_url if base_url.endswith("/responses") else f"{base_url}/responses"
    with httpx.Client(timeout=20.0) as client:
        response = client.post(
            responses_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=request_payload,
        )
    response.raise_for_status()
    return response.json()


def _request_local_signal_extraction(scrape: ScrapeResult) -> dict[str, Any]:
    base_url = _local_base_url()
    chat_url = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("AI_SIGNAL_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request_payload = {
        "model": os.getenv("AI_SIGNAL_MODEL", os.getenv("OPENAI_SIGNAL_MODEL", DEFAULT_LOCAL_SIGNAL_MODEL)),
        "messages": [
            {
                "role": "system",
                "content": (
                    "You extract competitive-intelligence signals from scraped web page evidence. "
                    "Return strict JSON only with keys: company_name, summary, features, tools, "
                    "confidence, notes. Features and tools must be arrays of objects with keys "
                    "name, category, confidence, evidence. Do not infer unsupported capabilities."
                ),
            },
            {"role": "user", "content": _build_signal_prompt(scrape=scrape)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }

    with httpx.Client(timeout=40.0) as client:
        response = client.post(chat_url, headers=headers, json=request_payload)
    response.raise_for_status()
    return _chat_completion_to_responses_payload(response.json())


def _chat_completion_to_responses_payload(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return {}
    first = choices[0]
    if not isinstance(first, dict):
        return {}
    message = first.get("message")
    if not isinstance(message, dict):
        return {}
    content = message.get("content")
    if not isinstance(content, str):
        return {}
    return {"output_text": content}


def _ai_signal_provider() -> str:
    return os.getenv("AI_SIGNAL_PROVIDER", "openai").lower()


def _local_base_url() -> str:
    return (
        os.getenv("AI_SIGNAL_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or DEFAULT_LOCAL_BASE_URL
    ).rstrip("/")


def _build_signal_prompt(scrape: ScrapeResult) -> str:
    evidence = "\n".join(
        [
            f"Final URL: {scrape.final_url}",
            f"Source type: {scrape.source_type}",
            f"Detected company: {scrape.company_name}",
            f"Page title: {scrape.page_title or ''}",
            f"Meta description: {scrape.meta_description or ''}",
            "Headings:",
            "\n".join(f"- {heading}" for heading in scrape.headings[:14]),
            f"Summary: {scrape.summary or ''}",
        ]
    )
    evidence = evidence[:AI_SIGNAL_CONTEXT_CHARS]
    return (
        "Extract strict JSON for features and tools/platforms from this page evidence.\n"
        "Return two signal arrays: features for what the vendor product does, and tools for named platforms, "
        "clouds, data stores, applications, or integrations it runs on or connects with.\n"
        "Prioritize these feature taxonomies when evidence supports them: Data Fabric, Data Governance, "
        "Workflow Automation, Compliance Reporting, AI Security Controls, Sensitive Data Discovery, "
        "Data Security Posture Management, Data Classification, Privacy Management, and Risk Analytics.\n"
        "Infer concrete capabilities from semantic evidence. For example, finding or cataloging sensitive records "
        "means Sensitive Data Discovery and Data Classification; audit-ready logs for GDPR/SOX means Compliance Reporting.\n"
        "Prioritize these tool taxonomies when explicitly mentioned as supported environments or integrations: "
        "AWS, Google Cloud, Azure, Snowflake, Databricks, Salesforce, Google Workspace, Microsoft 365, Slack, "
        "ServiceNow, Jira, Confluence, and Okta.\n"
        "Do not extract buzzwords such as digital transformation, next-gen architecture, or synergy. "
        "Do not extract cookie/footer/admin tools such as CookieBot, Google Analytics, WordPress, or tag managers. "
        "Do not extract internal programming languages unless framed as a user-facing plugin or integration.\n"
        "Use confidence from 0.0 to 1.0. Keep each evidence field short.\n\n"
        f"{evidence}"
    )


def _parse_signal_extraction(payload: dict[str, Any]) -> AISignalExtraction | None:
    output_text = _response_output_text(payload)
    if not output_text:
        return None

    parsed = json.loads(output_text)
    if not isinstance(parsed, dict):
        return None

    return AISignalExtraction(
        company_name=_string_value(parsed.get("company_name")),
        summary=_string_value(parsed.get("summary")),
        features=_parse_hits(parsed.get("features")),
        tools=_parse_hits(parsed.get("tools")),
        confidence=_confidence_value(parsed.get("confidence")),
        notes=_string_value(parsed.get("notes")),
    )


def _response_output_text(payload: dict[str, Any]) -> str | None:
    direct_text = payload.get("output_text")
    if isinstance(direct_text, str):
        return direct_text

    for output_item in payload.get("output", []):
        if not isinstance(output_item, dict):
            continue
        for content_item in output_item.get("content", []):
            if not isinstance(content_item, dict):
                continue
            text = content_item.get("text")
            if isinstance(text, str):
                return text
    return None


def _parse_hits(value: Any) -> list[AISignalHit]:
    if not isinstance(value, list):
        return []
    hits: list[AISignalHit] = []
    for item in value[:20]:
        if not isinstance(item, dict):
            continue
        name = _string_value(item.get("name"))
        category = _string_value(item.get("category"))
        confidence = _confidence_value(item.get("confidence"))
        evidence = _string_value(item.get("evidence"))
        if not name or not category or confidence < AI_MIN_SIGNAL_CONFIDENCE:
            continue
        hits.append(
            AISignalHit(
                name=name[:120],
                category=category[:80],
                confidence=confidence,
                evidence=evidence[:240],
            )
        )
    return hits


def _string_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _confidence_value(value: Any) -> float:
    if isinstance(value, int | float):
        return max(0.0, min(float(value), 1.0))
    return 0.0
