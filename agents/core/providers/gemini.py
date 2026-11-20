"""Provider Google Gemini (Generative Language API) via ``httpx``.

Particularites gerees ici :

* le prompt systeme est un champ separe (``systemInstruction``) ;
* les roles sont ``user`` / ``model`` (pas ``assistant``) ;
* un resultat d'outil est un bloc ``functionResponse`` **sans identifiant** :
  c'est le nom de la fonction qui fait le lien, contrairement a OpenAI ;
* une requete peut etre bloquee par les filtres de securite, auquel cas
  ``promptFeedback.blockReason`` doit produire une erreur explicite plutot
  qu'une reponse vide.
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


def to_gemini_payload(
    messages: Sequence[Message],
    *,
    max_tokens: int,
    temperature: float = 0.0,
    tools: Sequence[ToolSchema] | None = None,
) -> dict[str, Any]:
    """Construit le corps de requete ``models/{model}:generateContent``."""
    system_parts = [message.content for message in messages if message.role == "system"]
    contents: list[dict[str, Any]] = []

    for message in messages:
        if message.role == "system":
            continue
        if message.role == "tool":
            block = {
                "functionResponse": {
                    "name": message.name or "outil",
                    "response": {"result": message.content},
                }
            }
            if contents and contents[-1]["role"] == "user" and _is_function_response(contents[-1]):
                contents[-1]["parts"].append(block)
            else:
                contents.append({"role": "user", "parts": [block]})
            continue
        if message.role == "assistant" and message.tool_calls:
            parts: list[dict[str, Any]] = []
            if message.content:
                parts.append({"text": message.content})
            parts.extend(
                {"functionCall": {"name": call.name, "args": call.arguments}}
                for call in message.tool_calls
            )
            contents.append({"role": "model", "parts": parts})
            continue
        role = "model" if message.role == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": message.content}]})

    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    if system_parts:
        payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
    if tools:
        payload["tools"] = [
            {
                "functionDeclarations": [
                    {
                        "name": schema["name"],
                        "description": schema.get("description", ""),
                        "parameters": schema.get(
                            "input_schema",
                            {"type": "object", "properties": {}, "required": []},
                        ),
                    }
                    for schema in tools
                ]
            }
        ]
    return payload


def _is_function_response(content: Mapping[str, Any]) -> bool:
    parts = content.get("parts") or []
    return bool(parts) and all("functionResponse" in part for part in parts)


def parse_gemini_response(payload: Mapping[str, Any], *, model: str = "") -> LLMResponse:
    """Analyse une reponse ``generateContent`` (texte, functionCall, usage, blocage)."""
    block_reason = (payload.get("promptFeedback") or {}).get("blockReason")
    if block_reason:
        raise ProviderError(
            f"requete bloquee par Gemini: {block_reason}",
            hint="reformuler la demande sans contenu sensible",
        )

    candidates = payload.get("candidates") or []
    if not candidates:
        raise ProviderError(
            "reponse Gemini sans 'candidates'",
            hint="verifier le nom du modele et la cle API",
        )
    candidate = candidates[0]
    parts = (candidate.get("content") or {}).get("parts") or []

    texts: list[str] = []
    tool_calls: list[ToolCall] = []
    for index, part in enumerate(parts):
        if not isinstance(part, Mapping):
            continue
        if "text" in part:
            texts.append(str(part["text"]))
        elif "functionCall" in part:
            raw_call = part["functionCall"] or {}
            arguments = raw_call.get("args") or {}
            if not isinstance(arguments, Mapping):
                arguments = {"value": arguments}
            tool_calls.append(
                ToolCall(
                    name=str(raw_call.get("name", "")),
                    arguments=dict(arguments),
                    id=f"gemini_{index}",
                )
            )

    text = "\n".join(part for part in texts if part).strip()
    usage_meta = payload.get("usageMetadata") or {}
    prompt_tokens = int(usage_meta.get("promptTokenCount") or 0)
    completion_tokens = int(usage_meta.get("candidatesTokenCount") or 0)
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
        provider="gemini",
        model=str(payload.get("modelVersion") or model),
        finish_reason=str(candidate.get("finishReason") or "STOP"),
    )


class GeminiProvider:
    """Client minimal de l'API Generative Language."""

    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gemini-2.0-flash",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
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
                "GEMINI_API_KEY (ou GOOGLE_API_KEY) absente",
                hint="export GEMINI_API_KEY=... ou utilisez --provider mock",
            )
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - dependance optionnelle
            raise ProviderError(
                "httpx n'est pas installe",
                hint="pip install -e '.[providers]'",
            ) from exc

        body = to_gemini_payload(
            messages, max_tokens=max_tokens, temperature=temperature, tools=tools
        )
        started = asyncio.get_running_loop().time()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(
                    f"{self.base_url}/models/{self.model}:generateContent",
                    headers={
                        "x-goog-api-key": self.api_key,
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
        except httpx.TimeoutException as exc:
            raise RetryableProviderError("timeout Gemini", hint="reduire max_steps") from exc
        except httpx.HTTPError as exc:
            raise RetryableProviderError(f"erreur reseau Gemini: {exc}") from exc

        latency_ms = (asyncio.get_running_loop().time() - started) * 1000
        if response.status_code == 429 or response.status_code >= 500:
            raise RetryableProviderError(
                f"Gemini {response.status_code}: {response.text[:200]}",
                hint="quota ou indisponibilite temporaire",
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"Gemini {response.status_code}: {response.text[:300]}",
                hint="verifier le nom du modele et la cle API",
            )

        parsed = parse_gemini_response(response.json(), model=self.model)
        parsed.latency_ms = latency_ms
        return parsed


def dumps(payload: Mapping[str, Any]) -> str:  # pragma: no cover - utilitaire de debug
    """Serialisation stable pour les traces et le debogage."""
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
