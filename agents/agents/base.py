"""Classe de base des agents : boucle ReAct bornee et instrumentee.

La boucle est volontairement stricte :

* nombre d'etapes plafonne (``max_steps``) puis **finalisation forcee** sans
  outil, pour garantir une reponse texte ;
* chaque appel LLM est impute au budget partage ;
* une erreur d'outil est renvoyee au modele comme observation ("ERREUR: ..."),
  ce qui lui permet de se corriger, au lieu de faire echouer la tache ;
* les appels d'outils d'une meme etape sont executes **en parallele**.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, ClassVar

from agents.core.budget import Budget
from agents.core.bus import EventBus, NullSink
from agents.core.errors import ToolError
from agents.core.llm import LLMProvider, ToolSchema
from agents.core.models import LLMResponse, Message, ToolCall, Usage
from agents.core.registry import ToolRegistry

FINALIZE_INSTRUCTION = (
    "Limite d'etapes atteinte. Reponds maintenant, en francais, SANS appeler d'outil : "
    "synthetise ce qui a ete obtenu et signale explicitement ce qui manque."
)


class Agent:
    """Socle commun : prompt systeme, boucle ReAct, appels d'outils traces."""

    role: ClassVar[str] = "assistant"
    SYSTEM_PROMPT: ClassVar[str] = "Tu es un agent utile et concis."

    def __init__(
        self,
        provider: LLMProvider,
        *,
        registry: ToolRegistry | None = None,
        budget: Budget | None = None,
        bus: EventBus | None = None,
        max_steps: int = 4,
        max_tool_output_chars: int = 4000,
        temperature: float = 0.0,
        max_tokens: int = 900,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps doit etre >= 1")
        self.provider = provider
        self.registry = registry
        self.budget = budget or Budget()
        self.bus = bus or EventBus([NullSink()])
        self.max_steps = max_steps
        self.max_tool_output_chars = max_tool_output_chars
        self.temperature = temperature
        self.max_tokens = max_tokens

    # ------------------------------------------------------------- prompts
    def system_prompt(self) -> str:
        """Prompt systeme ; surchargeable par les sous-classes."""
        return self.SYSTEM_PROMPT

    def _tool_schemas(self, allowed: Sequence[str] | None) -> list[dict[str, Any]]:
        if self.registry is None:
            return []
        return self.registry.schemas(allowed)

    # ---------------------------------------------------------- appels LLM
    async def _complete(
        self,
        messages: Sequence[Message],
        tools: list[ToolSchema] | None,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.budget.check_deadline()
        self.bus.emit(
            "llm.request",
            agent=self.role,
            messages=len(messages),
            tools=len(tools or []),
            task_id=(metadata or {}).get("task_id"),
        )
        response = await self.provider.complete(
            messages,
            tools=tools or None,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            metadata={**(metadata or {}), "agent_role": self.role},
        )
        await self.budget.consume(response.usage)
        self.bus.emit(
            "llm.response",
            agent=self.role,
            provider=response.provider,
            text_chars=len(response.text),
            tool_calls=len(response.tool_calls),
            tokens=response.usage.total_tokens,
        )
        return response

    async def _invoke_tool(
        self,
        call: ToolCall,
        *,
        allowed: set[str] | None,
        task_id: str | None,
    ) -> str:
        """Execute un outil et transforme toute erreur en observation lisible."""
        if self.registry is None:
            return f"ERREUR: aucun outil n'est disponible pour l'agent {self.role}"
        if allowed is not None and call.name not in allowed:
            return (
                f"ERREUR: l'outil {call.name!r} n'est pas autorise pour cette tache. "
                f"Outils autorises: {', '.join(sorted(allowed)) or 'aucun'}"
            )
        self.bus.emit(
            "tool.call",
            agent=self.role,
            tool=call.name,
            arguments=call.arguments,
            task_id=task_id,
        )
        try:
            output = await self.registry.invoke(call.name, call.arguments)
        except ToolError as exc:
            message = f"ERREUR: {exc.message}"
            if exc.hint:
                message += f" (indice: {exc.hint})"
            self.bus.emit("tool.result", agent=self.role, tool=call.name, error=exc.message)
            return message
        self.bus.emit(
            "tool.result", agent=self.role, tool=call.name, chars=len(output), task_id=task_id
        )
        return output[: self.max_tool_output_chars]

    # --------------------------------------------------------- boucle ReAct
    async def react(
        self,
        messages: list[Message],
        *,
        allowed_tools: Sequence[str] | None = None,
        max_steps: int | None = None,
        task_id: str | None = None,
    ) -> tuple[str, int, Usage]:
        """Execute la boucle raisonnement/outils et retourne (texte, etapes, usage)."""
        steps_limit = max_steps or self.max_steps
        allowed = set(allowed_tools) if allowed_tools is not None else None
        schemas = self._tool_schemas(allowed_tools)
        usage = Usage()
        metadata = {"task_id": task_id, "agent_role": self.role}

        for step in range(1, steps_limit + 1):
            response = await self._complete(messages, schemas, metadata=metadata)
            usage = usage + response.usage
            calls = [
                call.with_id(call.id or f"{task_id or 'run'}-s{step}-c{index}")
                for index, call in enumerate(response.tool_calls)
            ]
            messages.append(
                Message(
                    role="assistant",
                    content=response.text,
                    tool_calls=tuple(calls),
                )
            )
            if not calls:
                return response.text.strip(), step, usage

            outputs = await asyncio.gather(
                *(self._invoke_tool(call, allowed=allowed, task_id=task_id) for call in calls)
            )
            for call, output in zip(calls, outputs, strict=True):
                messages.append(
                    Message(
                        role="tool",
                        content=output,
                        name=call.name,
                        tool_call_id=call.id,
                    )
                )

        self.bus.emit("agent.finalize", agent=self.role, task_id=task_id, steps=steps_limit)
        messages.append(Message(role="user", content=FINALIZE_INSTRUCTION))
        response = await self._complete(messages, None, metadata=metadata)
        usage = usage + response.usage
        return response.text.strip(), steps_limit + 1, usage
