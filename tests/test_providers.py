"""Tests des providers : determinisme du mock, retries, conversions d'API."""

from __future__ import annotations

import asyncio

import pytest
from agents.core.errors import ProviderError, RetryableProviderError
from agents.core.llm import RetryingProvider, build_provider
from agents.core.models import LLMResponse, Message, ToolCall, Usage
from agents.core.providers.anthropic import parse_anthropic_response, to_anthropic_payload
from agents.core.providers.mock import MockProvider
from agents.core.providers.openai import (
    parse_openai_response,
    to_openai_messages,
    to_openai_tools,
)
from agents.core.providers.scripted import ScriptedProvider

MESSAGES = [Message(role="system", content="PLANNER"), Message(role="user", content="oi")]


def test_mock_is_deterministic() -> None:
    provider = MockProvider()
    first = asyncio.run(provider.complete(MESSAGES, metadata={"agent_role": "planner"}))
    second = asyncio.run(provider.complete(MESSAGES, metadata={"agent_role": "planner"}))
    assert first.text == second.text
    assert first.usage.llm_calls == 1


def test_mock_detects_role_from_system_prompt() -> None:
    provider = MockProvider()
    response = asyncio.run(provider.complete(MESSAGES))
    assert '"tasks"' in response.text


def test_mock_emits_tool_call_for_maths() -> None:
    provider = MockProvider()
    messages = [
        Message(role="system", content="WORKER"),
        Message(role="user", content="[[INSTRUCTION]]\nCalcule 12*249.99"),
    ]
    response = asyncio.run(provider.complete(messages, tools=[{"name": "calc_evaluate"}]))
    assert response.tool_calls[0].name == "calc_evaluate"
    assert response.tool_calls[0].arguments["expression"] == "12*249.99"


def test_scripted_provider_sequences_and_exhaustion() -> None:
    provider = ScriptedProvider(script=[LLMResponse(text="a"), LLMResponse(text="b")])
    assert asyncio.run(provider.complete(MESSAGES)).text == "a"
    assert asyncio.run(provider.complete(MESSAGES)).text == "b"
    with pytest.raises(ProviderError, match="script epuise"):
        asyncio.run(provider.complete(MESSAGES))


def test_scripted_provider_can_raise_scripted_errors() -> None:
    provider = ScriptedProvider(script=[RetryableProviderError("429")])
    with pytest.raises(RetryableProviderError):
        asyncio.run(provider.complete(MESSAGES))


def test_retry_then_success() -> None:
    async def no_sleep(_: float) -> None:
        return None

    provider = RetryingProvider(
        ScriptedProvider(script=[RetryableProviderError("429"), LLMResponse(text="ok")]),
        max_attempts=3,
        sleep=no_sleep,
    )
    assert asyncio.run(provider.complete(MESSAGES)).text == "ok"
    assert provider.attempts_made == 2


def test_no_retry_on_permanent_error() -> None:
    async def no_sleep(_: float) -> None:
        return None

    provider = RetryingProvider(
        ScriptedProvider(script=[ProviderError("400"), LLMResponse(text="jamais")]),
        max_attempts=3,
        sleep=no_sleep,
    )
    with pytest.raises(ProviderError, match="400"):
        asyncio.run(provider.complete(MESSAGES))
    assert provider.attempts_made == 1


def test_retry_exhaustion_is_reported() -> None:
    async def no_sleep(_: float) -> None:
        return None

    provider = RetryingProvider(
        ScriptedProvider(script=[RetryableProviderError("429"), RetryableProviderError("429")]),
        max_attempts=2,
        sleep=no_sleep,
    )
    with pytest.raises(ProviderError, match="echec apres 2 tentatives"):
        asyncio.run(provider.complete(MESSAGES))


def test_retry_callback_is_called() -> None:
    async def no_sleep(_: float) -> None:
        return None

    seen: list[int] = []
    provider = RetryingProvider(
        ScriptedProvider(script=[RetryableProviderError("429"), LLMResponse(text="ok")]),
        max_attempts=2,
        sleep=no_sleep,
        on_retry=lambda attempt, exc, delay: seen.append(attempt),
    )
    asyncio.run(provider.complete(MESSAGES))
    assert seen == [1]


def test_build_provider_variants() -> None:
    assert isinstance(build_provider("mock"), MockProvider)
    assert isinstance(build_provider("offline"), MockProvider)
    assert isinstance(
        build_provider("openai:gpt-4o-mini", env={"OPENAI_API_KEY": "k"}), RetryingProvider
    )
    assert isinstance(build_provider("anthropic", env={"ANTHROPIC_API_KEY": "k"}), RetryingProvider)
    with pytest.raises(ProviderError, match="inconnu"):
        build_provider("mistral")


def test_openai_missing_key_fails_with_hint() -> None:
    provider = build_provider("openai", env={})
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        asyncio.run(provider.complete(MESSAGES))


def test_openai_message_conversion_keeps_tool_links() -> None:
    messages = [
        Message(role="system", content="sys"),
        Message(
            role="assistant",
            content="",
            tool_calls=(ToolCall(name="calc_evaluate", arguments={"expression": "1+1"}, id="c1"),),
        ),
        Message(role="tool", content="2", name="calc_evaluate", tool_call_id="c1"),
    ]
    payload = to_openai_messages(messages)
    assert payload[1]["tool_calls"][0]["id"] == "c1"
    assert payload[1]["tool_calls"][0]["function"]["arguments"] == '{"expression": "1+1"}'
    assert payload[2] == {"role": "tool", "tool_call_id": "c1", "content": "2"}


def test_openai_tools_conversion() -> None:
    tools = to_openai_tools(
        [{"name": "t", "description": "d", "input_schema": {"type": "object", "properties": {}}}]
    )
    assert tools is not None
    assert tools[0]["function"]["name"] == "t"
    assert to_openai_tools([]) is None


def test_parse_openai_response_reads_tool_calls_and_usage() -> None:
    payload = {
        "model": "gpt-x",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "calc_evaluate",
                                "arguments": '{"expression": "2+2"}',
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    response = parse_openai_response(payload)
    assert response.tool_calls[0].arguments == {"expression": "2+2"}
    assert response.usage.total_tokens == 15
    assert response.model == "gpt-x"


def test_parse_openai_response_survives_broken_arguments() -> None:
    payload = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [{"id": "c", "function": {"name": "f", "arguments": "{oops"}}],
                }
            }
        ]
    }
    response = parse_openai_response(payload)
    assert response.tool_calls[0].arguments["__raw_arguments"] == "{oops"


def test_parse_openai_response_without_choices() -> None:
    with pytest.raises(ProviderError, match="choices"):
        parse_openai_response({})


def test_anthropic_payload_structure() -> None:
    payload = to_anthropic_payload(
        [
            Message(role="system", content="sys"),
            Message(role="user", content="question"),
            Message(
                role="assistant",
                content="",
                tool_calls=(
                    ToolCall(name="calc_evaluate", arguments={"expression": "2"}, id="t1"),
                ),
            ),
            Message(role="tool", content="2", name="calc_evaluate", tool_call_id="t1"),
        ],
        model="claude-x",
        max_tokens=100,
        tools=[{"name": "calc_evaluate", "description": "d", "input_schema": {"type": "object"}}],
    )
    assert payload["system"] == "sys"
    assert payload["max_tokens"] == 100
    roles = [message["role"] for message in payload["messages"]]
    assert roles == ["user", "assistant", "user"]
    assert payload["messages"][2]["content"][0]["type"] == "tool_result"
    assert payload["tools"][0]["name"] == "calc_evaluate"


def test_parse_anthropic_response() -> None:
    payload = {
        "model": "claude-x",
        "stop_reason": "tool_use",
        "content": [
            {"type": "text", "text": "je calcule"},
            {
                "type": "tool_use",
                "id": "tu_1",
                "name": "calc_evaluate",
                "input": {"expression": "1+1"},
            },
        ],
        "usage": {"input_tokens": 7, "output_tokens": 3},
    }
    response = parse_anthropic_response(payload)
    assert response.text == "je calcule"
    assert response.tool_calls[0].id == "tu_1"
    assert response.usage.total_tokens == 10
    assert response.finish_reason == "tool_use"


def test_parse_anthropic_response_with_invalid_content() -> None:
    with pytest.raises(ProviderError):
        parse_anthropic_response({"content": "pas une liste"})


def test_usage_dataclass_defaults() -> None:
    response = LLMResponse()
    assert response.usage == Usage(0, 0, 0)
    assert response.tool_calls == []
