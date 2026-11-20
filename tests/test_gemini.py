"""Tests du provider Gemini : conversions pures, erreurs, factory."""

from __future__ import annotations

import asyncio

import pytest
from agents.core.errors import ProviderError
from agents.core.llm import RetryingProvider, build_provider
from agents.core.models import Message, ToolCall
from agents.core.providers.gemini import (
    GeminiProvider,
    parse_gemini_response,
    to_gemini_payload,
)


def test_payload_maps_roles_and_system() -> None:
    payload = to_gemini_payload(
        [
            Message(role="system", content="tu es utile"),
            Message(role="user", content="question"),
            Message(role="assistant", content="reponse"),
        ],
        max_tokens=100,
        temperature=0.3,
    )
    assert payload["systemInstruction"]["parts"][0]["text"] == "tu es utile"
    assert [item["role"] for item in payload["contents"]] == ["user", "model"]
    assert payload["generationConfig"] == {"temperature": 0.3, "maxOutputTokens": 100}


def test_payload_maps_tool_calls_and_results() -> None:
    payload = to_gemini_payload(
        [
            Message(role="user", content="calcule"),
            Message(
                role="assistant",
                content="",
                tool_calls=(
                    ToolCall(name="calc_evaluate", arguments={"expression": "1+1"}, id="x"),
                ),
            ),
            Message(role="tool", content="2", name="calc_evaluate", tool_call_id="x"),
        ],
        max_tokens=50,
    )
    assert payload["contents"][1]["parts"][0]["functionCall"] == {
        "name": "calc_evaluate",
        "args": {"expression": "1+1"},
    }
    assert payload["contents"][2]["parts"][0]["functionResponse"]["name"] == "calc_evaluate"


def test_payload_declares_tools() -> None:
    payload = to_gemini_payload(
        [Message(role="user", content="x")],
        max_tokens=10,
        tools=[{"name": "t", "description": "d", "input_schema": {"type": "object"}}],
    )
    declaration = payload["tools"][0]["functionDeclarations"][0]
    assert declaration["name"] == "t"
    assert declaration["parameters"] == {"type": "object"}


def test_parse_text_and_usage() -> None:
    payload = {
        "modelVersion": "gemini-2.0-flash",
        "candidates": [
            {
                "content": {"parts": [{"text": "bonjour "}, {"text": "monde"}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3},
    }
    response = parse_gemini_response(payload)
    assert response.text == "bonjour \nmonde"
    assert response.usage.total_tokens == 10
    assert response.provider == "gemini"
    assert response.model == "gemini-2.0-flash"


def test_parse_function_call() -> None:
    payload = {
        "candidates": [
            {"content": {"parts": [{"functionCall": {"name": "calc_evaluate", "args": {"x": 1}}}]}}
        ]
    }
    response = parse_gemini_response(payload)
    assert response.tool_calls[0].name == "calc_evaluate"
    assert response.tool_calls[0].arguments == {"x": 1}
    assert response.tool_calls[0].id == "gemini_0"


def test_parse_blocked_request() -> None:
    with pytest.raises(ProviderError, match="bloquee"):
        parse_gemini_response({"promptFeedback": {"blockReason": "SAFETY"}})


def test_parse_without_candidates() -> None:
    with pytest.raises(ProviderError, match="candidates"):
        parse_gemini_response({})


def test_factory_builds_gemini() -> None:
    provider = build_provider("gemini", env={"GEMINI_API_KEY": "k"})
    assert isinstance(provider, RetryingProvider)
    assert provider.name == "gemini"


def test_factory_accepts_google_alias_and_google_key() -> None:
    provider = build_provider("google:gemini-2.0-flash", env={"GOOGLE_API_KEY": "k"})
    inner = provider.inner
    assert isinstance(inner, GeminiProvider)
    assert inner.model == "gemini-2.0-flash"
    assert inner.api_key == "k"


def test_missing_key_is_explicit() -> None:
    provider = build_provider("gemini", env={})
    with pytest.raises(ProviderError, match="GEMINI_API_KEY"):
        asyncio.run(provider.complete([Message(role="user", content="bonjour")]))
