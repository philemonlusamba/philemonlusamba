"""Couche LLM : protocole commun, factory, wrapper de retry.

Le framework ne depend d'aucun SDK : les providers parlent HTTP via ``httpx``
(dependance optionnelle ``.[providers]``). Le provider ``mock`` est, lui, 100 %
stdlib et deterministe, ce qui permet de faire tourner exemples et tests hors
ligne, sans cle API et sans cout.
"""

from __future__ import annotations

import asyncio
import os
import random
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from agents.core.errors import ProviderError, RetryableProviderError
from agents.core.models import LLMResponse, Message

# Schema neutre d'outil, converti par chaque provider.
ToolSchema = Mapping[str, Any]


@runtime_checkable
class LLMProvider(Protocol):
    """Contrat minimal que doit respecter tout backend de modele."""

    name: str

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[ToolSchema] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 800,
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMResponse:
        """Retourne une reponse normalisee (texte et/ou appels d'outils)."""
        ...


def estimate_tokens(text: str) -> int:
    """Estimation grossiere mais stable (~4 caracteres par token)."""
    return max(1, len(text) // 4)


@dataclass
class RetryingProvider:
    """Ajoute des retries exponentiels aux erreurs transitoires d'un provider.

    Seules les :class:`RetryableProviderError` sont reessayees : une erreur de
    programmation ou de validation ne doit jamais etre rejouee silencieusement.
    """

    inner: LLMProvider
    max_attempts: int = 3
    base_delay: float = 0.25
    max_delay: float = 4.0
    jitter: float = 0.1
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    on_retry: Callable[[int, BaseException, float], None] | None = None
    attempts_made: int = field(default=0, init=False)

    @property
    def name(self) -> str:
        return getattr(self.inner, "name", "unknown")

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[ToolSchema] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 800,
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMResponse:
        last_error: BaseException | None = None
        for attempt in range(1, self.max_attempts + 1):
            self.attempts_made = attempt
            try:
                return await self.inner.complete(
                    messages,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    metadata=metadata,
                )
            except RetryableProviderError as exc:
                last_error = exc
                if attempt >= self.max_attempts:
                    break
                delay = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
                delay += random.uniform(0, self.jitter)
                if self.on_retry is not None:
                    self.on_retry(attempt, exc, delay)
                await self.sleep(delay)
        raise ProviderError(
            f"echec apres {self.max_attempts} tentatives: {last_error}",
            hint="verifier la cle API, le quota et la connectivite reseau",
        )


def build_provider(
    spec: str = "mock",
    *,
    env: Mapping[str, str] | None = None,
    max_attempts: int = 3,
    **kwargs: Any,
) -> LLMProvider:
    """Construit un provider depuis une specification ``"nom[:modele]"``.

    Exemples : ``mock``, ``openai:gpt-4o-mini``, ``anthropic:claude-3-5-sonnet-latest``,
    ``gemini:gemini-2.0-flash``.
    """
    environ = dict(os.environ if env is None else env)
    name, _, model = spec.partition(":")
    name = name.strip().lower()
    model = model.strip()

    if name in {"mock", "offline"}:
        from agents.core.providers.mock import MockProvider

        provider: LLMProvider = MockProvider(model=model or "mock-1")
        return provider

    if name == "openai":
        from agents.core.providers.openai import OpenAIProvider

        return RetryingProvider(
            OpenAIProvider(
                api_key=environ.get("OPENAI_API_KEY", ""),
                model=model or environ.get("AGENTS_MODEL", "gpt-4o-mini"),
                base_url=environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                **kwargs,
            ),
            max_attempts=max_attempts,
        )

    if name in {"anthropic", "claude"}:
        from agents.core.providers.anthropic import AnthropicProvider

        return RetryingProvider(
            AnthropicProvider(
                api_key=environ.get("ANTHROPIC_API_KEY", ""),
                model=model or environ.get("AGENTS_MODEL", "claude-3-5-sonnet-latest"),
                base_url=environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"),
                **kwargs,
            ),
            max_attempts=max_attempts,
        )

    if name in {"gemini", "google"}:
        from agents.core.providers.gemini import GeminiProvider

        return RetryingProvider(
            GeminiProvider(
                api_key=environ.get("GEMINI_API_KEY") or environ.get("GOOGLE_API_KEY", ""),
                model=model or environ.get("AGENTS_MODEL", "gemini-2.0-flash"),
                base_url=environ.get(
                    "GEMINI_BASE_URL",
                    "https://generativelanguage.googleapis.com/v1beta",
                ),
                **kwargs,
            ),
            max_attempts=max_attempts,
        )

    raise ProviderError(
        f"provider inconnu: {spec!r}",
        hint="valeurs acceptees: mock, openai[:modele], anthropic[:modele], gemini[:modele]",
    )
