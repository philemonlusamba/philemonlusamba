"""Provider OpenAI (Chat Completions) via ``httpx``.

La conversion de messages et l'analyse de la reponse sont des fonctions pures et
testables ; seule la couche HTTP est intraçable sans cle API.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Any

from agents.core.errors import ProviderError, RetryableProviderError
from agents.core.llm import ToolSchema, estimate_tokens
from agents.core.models import LLMResponse, Message, ToolCall, Usage

DEFAULT_TIMEOUT_S = 60.0


def to_openai_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Convertit les messages internes au format Chat Completions."""
    payload: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "tool":
            payload.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id or message.name or "call_0",
                    "content": message.content,
                }
            )
        elif message.role == "assistant" and message.tool_calls:
            payload.append(
                {
                    "role": "assistant",
                    "content": message.content or None,
                    "tool_calls": [
                        {
                            "id": call.id or f"call_{index}",
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments, ensure_ascii=False),
                            },
                        }
                        for index, call in enumerate(message.tool_calls)
                    ],
                }
            )
        else:
            payload.append({"role": message.role, "content": message.content})
    return payload


def to_openai_tools(tools: Sequence[ToolSchema] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": schema.get("description", ""),
                "parameters": schema.get(
                    "input_schema", {"type": "object", "properties": {}, "required": []}
                ),
            },
        }
        for schema in tools
    ]


def parse_openai_response(payload: Mapping[str, Any], *, model: str = "") -> LLMResponse:
    """Analyse une reponse Chat Completions, en tolerant les champs absents."""
    choices = payload.get("choices") or []
    if not choices:
        raise ProviderError(
            "reponse OpenAI sans 'choices'",
            hint="verifier le modele et les parametres envoyes",
        )
    choice = choices[0]
    message = choice.get("message") or {}
    text = (message.get("content") or "").strip()

    tool_calls: list[ToolCall] = []
    for index, raw_call in enumerate(message.get("tool_calls") or []):
        function = raw_call.get("function") or {}
        raw_args = function.get("arguments") or "{}"
        try:
            arguments = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except json.JSONDecodeError:
            arguments = {"__raw_arguments": raw_args}
        if not isinstance(arguments, dict):
            arguments = {"value": arguments}
        tool_calls.append(
            ToolCall(
                name=str(function.get("name", "")),
                arguments=arguments,
                id=str(raw_call.get("id") or f"call_{index}"),
            )
        )

    raw_usage = payload.get("usage") or {}
    prompt_tokens = int(raw_usage.get("prompt_tokens") or 0)
    completion_tokens = int(raw_usage.get("completion_tokens") or 0)
    if prompt_tokens == 0:
        prompt_tokens = estimate_tokens(text)

    return LLMResponse(
        text=text,
        tool_calls=tool_calls,
        usage=Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            llm_calls=1,
        ),
        provider="openai",
        model=str(payload.get("model") or model),
        finish_reason=str(choice.get("finish_reason") or "stop"),
    )


class OpenAIProvider:
    """Client minimal, sans dependance au SDK officiel."""

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[ToolSchema] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 800,
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMResponse:
        if not self.api_key:
            raise ProviderError(
                "OPENAI_API_KEY absente",
                hint="export OPENAI_API_KEY=... ou utilisez --provider mock",
            )
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - dependance optionnelle
            raise ProviderError(
                "httpx n'est pas installe",
                hint="pip install -e '.[providers]'",
            ) from exc

        body: dict[str, Any] = {
            "model": self.model,
            "messages": to_openai_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        tools_payload = to_openai_tools(tools)
        if tools_payload:
            body["tools"] = tools_payload

        started = asyncio.get_running_loop().time()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
        except httpx.TimeoutException as exc:
            raise RetryableProviderError("timeout OpenAI", hint="reduire max_steps") from exc
        except httpx.HTTPError as exc:
            raise RetryableProviderError(f"erreur reseau OpenAI: {exc}") from exc

        latency_ms = (asyncio.get_running_loop().time() - started) * 1000
        if response.status_code == 429 or response.status_code >= 500:
            raise RetryableProviderError(
                f"OpenAI {response.status_code}: {response.text[:200]}",
                hint="quota ou indisponibilite temporaire",
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"OpenAI {response.status_code}: {response.text[:300]}",
                hint="verifier le nom du modele et le solde du compte",
            )

        parsed = parse_openai_response(response.json(), model=self.model)
        parsed.latency_ms = latency_ms
        return parsed
