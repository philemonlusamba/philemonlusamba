"""Provider Anthropic (Messages API) via ``httpx``.

Particularites geree ici : le prompt systeme est un champ separe, les resultats
d'outils sont des blocs ``tool_result`` dans un message ``user``, et l'API exige
un ``max_tokens`` explicite.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Any

from agents.core.errors import ProviderError, RetryableProviderError
from agents.core.llm import ToolSchema, estimate_tokens
from agents.core.models import LLMResponse, Message, ToolCall, Usage

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_TIMEOUT_S = 60.0


def to_anthropic_payload(
    messages: Sequence[Message],
    *,
    model: str,
    max_tokens: int,
    temperature: float = 0.0,
    tools: Sequence[ToolSchema] | None = None,
) -> dict[str, Any]:
    """Construit le corps de requete ``/v1/messages``."""
    system_parts = [message.content for message in messages if message.role == "system"]
    converted: list[dict[str, Any]] = []

    for message in messages:
        if message.role == "system":
            continue
        if message.role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": message.tool_call_id or message.name or "toolu_0",
                "content": message.content,
            }
            if (
                converted
                and converted[-1]["role"] == "user"
                and isinstance(converted[-1]["content"], list)
            ):
                converted[-1]["content"].append(block)
            else:
                converted.append({"role": "user", "content": [block]})
            continue
        if message.role == "assistant" and message.tool_calls:
            content: list[dict[str, Any]] = []
            if message.content:
                content.append({"type": "text", "text": message.content})
            content.extend(
                {
                    "type": "tool_use",
                    "id": call.id or f"toolu_{index}",
                    "name": call.name,
                    "input": call.arguments,
                }
                for index, call in enumerate(message.tool_calls)
            )
            converted.append({"role": "assistant", "content": content})
            continue
        converted.append({"role": message.role, "content": message.content})

    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": converted,
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    if tools:
        payload["tools"] = [
            {
                "name": schema["name"],
                "description": schema.get("description", ""),
                "input_schema": schema.get(
                    "input_schema", {"type": "object", "properties": {}, "required": []}
                ),
            }
            for schema in tools
        ]
    return payload


def parse_anthropic_response(payload: Mapping[str, Any], *, model: str = "") -> LLMResponse:
    """Analyse une reponse Messages : concatene les blocs texte, extrait les tool_use."""
    blocks = payload.get("content") or []
    if not isinstance(blocks, list):
        raise ProviderError("reponse Anthropic: 'content' n'est pas une liste")

    texts: list[str] = []
    tool_calls: list[ToolCall] = []
    for index, block in enumerate(blocks):
        if not isinstance(block, Mapping):
            continue
        if block.get("type") == "text":
            texts.append(str(block.get("text", "")))
        elif block.get("type") == "tool_use":
            raw_input = block.get("input") or {}
            if isinstance(raw_input, str):
                try:
                    raw_input = json.loads(raw_input)
                except json.JSONDecodeError:
                    raw_input = {"__raw_input": raw_input}
            tool_calls.append(
                ToolCall(
                    name=str(block.get("name", "")),
                    arguments=dict(raw_input) if isinstance(raw_input, Mapping) else {},
                    id=str(block.get("id") or f"toolu_{index}"),
                )
            )

    raw_usage = payload.get("usage") or {}
    prompt_tokens = int(raw_usage.get("input_tokens") or 0)
    completion_tokens = int(raw_usage.get("output_tokens") or 0)
    text = "\n".join(part for part in texts if part).strip()
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
        provider="anthropic",
        model=str(payload.get("model") or model),
        finish_reason=str(payload.get("stop_reason") or "stop"),
    )


class AnthropicProvider:
    """Client minimal de l'API Messages."""

    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-3-5-sonnet-latest",
        base_url: str = "https://api.anthropic.com/v1",
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
                "ANTHROPIC_API_KEY absente",
                hint="export ANTHROPIC_API_KEY=... ou utilisez --provider mock",
            )
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - dependance optionnelle
            raise ProviderError(
                "httpx n'est pas installe",
                hint="pip install -e '.[providers]'",
            ) from exc

        body = to_anthropic_payload(
            messages,
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
        )
        started = asyncio.get_running_loop().time()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(
                    f"{self.base_url}/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": ANTHROPIC_VERSION,
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
        except httpx.TimeoutException as exc:
            raise RetryableProviderError("timeout Anthropic", hint="reduire max_steps") from exc
        except httpx.HTTPError as exc:
            raise RetryableProviderError(f"erreur reseau Anthropic: {exc}") from exc

        latency_ms = (asyncio.get_running_loop().time() - started) * 1000
        if response.status_code == 429 or response.status_code >= 500:
            raise RetryableProviderError(
                f"Anthropic {response.status_code}: {response.text[:200]}",
                hint="quota ou indisponibilite temporaire",
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"Anthropic {response.status_code}: {response.text[:300]}",
                hint="verifier le nom du modele et la cle API",
            )

        parsed = parse_anthropic_response(response.json(), model=self.model)
        parsed.latency_ms = latency_ms
        return parsed
