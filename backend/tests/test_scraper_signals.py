from __future__ import annotations

import base64

import httpx

from app import main
from app.models import CompanySource
from app.scraper import (
    _dedupe_feature_hits,
    _dedupe_tool_hits,
    _domain_feature_hints,
    _domain_tool_hints,
    _extract_features,
    _extract_tools,
    resolve_google_news_article_url,
)


def _feature_names(text: str) -> set[str]:
    return {item.name for item in _extract_features(text)}


def _tool_names(text: str) -> set[str]:
    return {item.name for item in _extract_tools(text)}


def test_exposure_management_signals_are_detected() -> None:
    text = (
        "Vulnerability and exposure management. Cloud and AI security. "
        "Tenable One unifies visibility across hybrid attack surfaces and reduces cyber risk."
    )

    features = _feature_names(text)
    tools = _tool_names(text)

    assert "Exposure Management" in features
    assert "Vulnerability Management" in features
    assert "Cloud Security" in features
    assert "AI Security Controls" in features
    assert "Attack Surface Management" in features
    assert "Cyber Risk Reduction" in features
    assert "Tenable One" in tools


def test_workflow_automation_signals_are_detected() -> None:
    text = (
        "Intellistack is an AI-native no-code workflow platform. Build forms, "
        "generate documents, collect eSignatures, and unify the contract lifecycle."
    )

    features = _feature_names(text)
    tools = _tool_names(text)

    assert "Workflow Automation" in features
    assert "No-Code Workflow Builder" in features
    assert "Document Generation" in features
    assert "Electronic Signature" in features
    assert "Contract Lifecycle Management" in features
    assert "Form Automation" in features
    assert "Intellistack" in tools


def test_semantic_data_governance_signals_are_detected() -> None:
    text = (
        "We automatically find and catalog sensitive records across your cloud storage. "
        "Teams get a unified data layer for data stewardship, risk dashboards, and "
        "audit-ready logs for GDPR/SOX compliance."
    )

    features = _feature_names(text)

    assert "Sensitive Data Discovery" in features
    assert "Data Classification" in features
    assert "Data Fabric" in features
    assert "Data Governance" in features
    assert "Risk Analytics" in features
    assert "Compliance Reporting" in features


def test_target_application_tools_are_detected() -> None:
    text = (
        "Native deployment on AWS and Azure with Snowflake synchronization. "
        "Supported integrations include Salesforce, Google Workspace, Microsoft 365, "
        "Slack, ServiceNow, Jira, Confluence, and Okta."
    )

    tools = _tool_names(text)

    assert {
        "AWS",
        "Azure",
        "Snowflake",
        "Salesforce",
        "Google Workspace",
        "Microsoft 365",
        "Slack",
        "ServiceNow",
        "Jira",
        "Confluence",
        "Okta",
    }.issubset(tools)


def test_cookie_and_footer_noise_does_not_create_tool_signals() -> None:
    text = (
        "Cookie Policy: Google Analytics, WordPress, and Okta may process administrator telemetry. "
        "Privacy Policy Terms of Use. All rights reserved."
    )

    assert _tool_names(text) == set()


def test_url_and_domain_hints_cover_sparse_or_blocked_sources() -> None:
    opentext_text = "https://www.opentext.com/products/data-security Access Denied"
    rubrik_features = _domain_feature_hints("https://www.rubrik.com/")
    rubrik_tools = _domain_tool_hints("https://www.rubrik.com/")
    opentext_features = _domain_feature_hints("https://www.opentext.com/")
    tenable_features = _domain_feature_hints("https://www.tenable.com/")
    tenable_tools = _domain_tool_hints("https://www.tenable.com/")

    features = _dedupe_feature_hits([*_extract_features(opentext_text), *rubrik_features, *opentext_features, *tenable_features])
    tools = _dedupe_tool_hits([*_extract_tools(opentext_text), *rubrik_tools, *tenable_tools])

    assert "Data Security" in {item.name for item in features}
    assert "Cyber Resilience" in {item.name for item in features}
    assert "Exposure Management" in {item.name for item in features}
    assert "Rubrik Security Cloud" in {item.name for item in tools}
    assert "Tenable One" in {item.name for item in tools}


def test_source_signal_fallback_populates_sparse_source_rows() -> None:
    source = CompanySource(
        source_url="https://www.tenable.com/",
        source_domain="www.tenable.com",
        source_type="website",
        detected_company_name="Tenable",
        extracted_features_json="[]",
        extracted_tools_json="[]",
        confidence=0.2,
    )

    features = {item.name for item in main._source_features(source)}
    tools = {item.name for item in main._source_tools(source)}

    assert "Exposure Management" in features
    assert "Vulnerability Management" in features
    assert "Tenable One" in tools


def _encoded_google_news_url(payload: bytes) -> str:
    article_id = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"https://news.google.com/rss/articles/{article_id}?oc=5"


def _varint(value: int) -> bytes:
    parts = []
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            parts.append(byte | 0x80)
        else:
            parts.append(byte)
            return bytes(parts)


def test_google_news_url_embedded_article_is_decoded() -> None:
    publisher_url = "https://publisher.example.com/article"
    payload = b'\x08\x13"' + _varint(len(publisher_url)) + publisher_url.encode() + b"\xd2\x01\x00"

    assert resolve_google_news_article_url(_encoded_google_news_url(payload)) == publisher_url


def test_google_news_url_batch_decode_fallback() -> None:
    publisher_url = "https://publisher.example.com/new-format-article"
    article_id = "AU_yqLopaqueid"
    payload = b'\x08\x13"' + _varint(len(article_id)) + article_id.encode()
    google_url = _encoded_google_news_url(payload)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(404)
        assert request.method == "POST"
        body = ')]}\'\n\n[[["Fbv4je","[\\"garturlres\\",\\"https:\\\\/\\\\/publisher.example.com\\\\/new-format-article\\",1]",null,null,null]]]'
        return httpx.Response(200, text=body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert resolve_google_news_article_url(google_url, client=client) == publisher_url


def test_google_news_url_signature_decode_path() -> None:
    publisher_url = "https://publisher.example.com/signature-format-article"
    article_id = "AU_yqLsignatureid"
    payload = b'\x08\x13"' + _varint(len(article_id)) + article_id.encode()
    google_url = _encoded_google_news_url(payload)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                text='<c-wiz><div jscontroller="x" data-n-a-sg="sig-value" data-n-a-ts="12345"></div></c-wiz>',
            )
        assert request.method == "POST"
        body = ')]}\'\n\n[[["wrb.fr","Fbv4je","[\\"garturlres\\",\\"https://publisher.example.com/signature-format-article\\"]",null,null,null]],["di",1],["af.httprm",1,"x",1]]'
        return httpx.Response(200, text=body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert resolve_google_news_article_url(google_url, client=client) == publisher_url
