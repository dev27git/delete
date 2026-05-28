from __future__ import annotations

import json

from app import main
from app.ai_enrichment import (
    AISignalExtraction,
    AISignalHit,
    _chat_completion_to_responses_payload,
    _parse_signal_extraction,
    ai_signal_extraction_enabled,
)
from app.scraper import FeatureHit, ScrapeResult


def test_ai_signal_extraction_is_disabled_without_flag(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AI_SIGNAL_EXTRACTION_ENABLED", "0")

    assert ai_signal_extraction_enabled() is False


def test_local_ai_signal_extraction_can_enable_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AI_SIGNAL_EXTRACTION_ENABLED", "1")
    monkeypatch.setenv("AI_SIGNAL_PROVIDER", "ollama")

    assert ai_signal_extraction_enabled() is True


def test_chat_completion_payload_is_parsed_like_response_output() -> None:
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "company_name": "LocalCo",
                            "summary": "Local model extraction.",
                            "features": [],
                            "tools": [],
                            "confidence": 0.7,
                            "notes": "Parsed from chat completion.",
                        }
                    )
                }
            }
        ]
    }

    responses_payload = _chat_completion_to_responses_payload(payload)
    result = _parse_signal_extraction(responses_payload)

    assert result is not None
    assert result.company_name == "LocalCo"


def test_parse_ai_signal_extraction_from_responses_payload() -> None:
    payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {
                                "company_name": "Tenable",
                                "summary": "Exposure management and AI security platform.",
                                "features": [
                                    {
                                        "name": "Exposure Management",
                                        "category": "Exposure",
                                        "confidence": 0.91,
                                        "evidence": "exposure management",
                                    }
                                ],
                                "tools": [
                                    {
                                        "name": "Tenable One",
                                        "category": "Exposure Management",
                                        "confidence": 0.88,
                                        "evidence": "Tenable One",
                                    }
                                ],
                                "confidence": 0.9,
                                "notes": "Supported by page title and headings.",
                            }
                        ),
                    }
                ],
            }
        ]
    }

    result = _parse_signal_extraction(payload)

    assert result is not None
    assert result.company_name == "Tenable"
    assert result.features[0].name == "Exposure Management"
    assert result.tools[0].name == "Tenable One"


def test_apply_ai_signal_enrichment_merges_scrape_signals(monkeypatch) -> None:
    scrape = ScrapeResult(
        http_status=200,
        final_url="https://www.example.com/",
        source_type="website",
        page_title="Example Security",
        meta_description="Cloud security platform",
        headings=["Platform"],
        summary=None,
        company_name="Example",
        publisher="Example",
        published_at=None,
        detected_features=[FeatureHit(name="Cloud Security", category="Cloud")],
        detected_tools=[],
        confidence=0.6,
    )

    monkeypatch.setattr(
        main,
        "extract_ai_signals",
        lambda _: AISignalExtraction(
            company_name="Example",
            summary="Example secures AI workflows.",
            features=[
                AISignalHit(
                    name="AI Security Controls",
                    category="AI Security",
                    confidence=0.87,
                    evidence="AI workflows",
                )
            ],
            tools=[
                AISignalHit(
                    name="Example Platform",
                    category="Security Platform",
                    confidence=0.8,
                    evidence="Example Security",
                )
            ],
            confidence=0.86,
            notes="Test extraction.",
        ),
    )

    main._apply_ai_signal_enrichment(scrape)

    assert {item.name for item in scrape.detected_features} == {"Cloud Security", "AI Security Controls"}
    assert {item.name for item in scrape.detected_tools} == {"Example Platform"}
    assert scrape.summary == "Example secures AI workflows."
    assert scrape.confidence == 0.65
