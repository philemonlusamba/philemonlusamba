"""Provider scripte : rejoue une sequence preparee de reponses ou d'exceptions.

Indispensable pour tester les chemins difficiles a obtenir avec un mock : retry
sur erreur transitoire, boucle ReAct de plusieurs etapes, quota epuise, sortie
JSON invalide du planner.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from agents.core.errors import ProviderError
from agents.core.llm import ToolSchema, estimate_tokens
from agents.core.models import LLMResponse, Message, Usage

Scripted = LLMResponse | BaseException | Any  # Any = callable(messages) -> LLMResponse


@dataclass
class ScriptedProvider:
    """Rejoue ``script`` reponse par reponse, dans l'ordre."""

    script: list[Scripted]
    name: str = "scripted"
    model: str = "scripted"
    calls: list[list[Message]] = field(default_factory=list)

    @property
    def remaining(self) -> int:
        return len(self.script)

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[ToolSchema] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 800,
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMResponse:
        self.calls.append(list(messages))
        if not self.script:
            raise ProviderError(
                "script epuise : le scenario de test attend moins d'appels LLM",
                hint="ajouter une reponse dans ScriptedProvider(script=[...])",
            )
        item = self.script.pop(0)
        await asyncio.sleep(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, LLMResponse):
            if item.usage.llm_calls == 0:
                item.usage = Usage(
                    prompt_tokens=estimate_tokens("".join(m.content for m in messages)),
                    completion_tokens=estimate_tokens(item.text),
                    llm_calls=1,
                )
            return item
        if isinstance(item, str):
            return LLMResponse(
                text=item,
                usage=Usage(prompt_tokens=10, completion_tokens=estimate_tokens(item), llm_calls=1),
                provider=self.name,
                model=self.model,
            )
        if callable(item):
            result = item(messages)
            return result if isinstance(result, LLMResponse) else LLMResponse(text=str(result))
        raise ProviderError(f"element de script non supporte: {type(item)!r}")
