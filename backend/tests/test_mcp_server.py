from __future__ import annotations

from app.mcp_server import _handle_request


def test_mcp_initialize_and_tool_list() -> None:
    initialize = _handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        }
    )
    tools = _handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

    assert initialize is not None
    assert initialize["result"]["serverInfo"]["name"] == "genai-competitive-analysis"
    assert tools is not None
    tool_names = {tool["name"] for tool in tools["result"]["tools"]}
    assert "competitive_list_companies" in tool_names
    assert "competitive_refresh_company" in tool_names
    assert "competitive_list_enrichment_connectors" in tool_names


def test_mcp_connector_tool_returns_configured_connectors() -> None:
    response = _handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "competitive_list_enrichment_connectors",
                "arguments": {},
            },
        }
    )

    assert response is not None
    content = response["result"]["content"][0]["text"]
    assert "OWASP GenAI Security" in content
    assert "Google Security Blog" in content
