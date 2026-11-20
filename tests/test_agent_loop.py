"""Tests de la boucle ReAct : outils, plafond d'etapes, feedback d'erreur, budget."""

from __future__ import annotations

import asyncio

import pytest
from agents.agents.base import Agent
from agents.core.budget import Budget
from agents.core.bus import CollectorSink, EventBus
from agents.core.errors import BudgetExceeded
from agents.core.models import LLMResponse, Message, ToolCall
from agents.core.providers.scripted import ScriptedProvider
from agents.core.registry import ToolRegistry


class Lab(Agent):
    """Agent minimal pour exercer la boucle."""

    role = "worker"
    SYSTEM_PROMPT = "Tu es un WORKER de test."

    async def run_loop(
        self, text: str, *, allowed: list[str] | None = None, max_steps: int = 3
    ) -> tuple[str, int]:
        messages = [
            Message(role="system", content=self.system_prompt()),
            Message(role="user", content=text),
        ]
        answer, steps, _ = await self.react(
            messages, allowed_tools=allowed, max_steps=max_steps, task_id="t1"
        )
        return answer, steps


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        name="calc_evaluate",
        description="calcul",
        input_schema={
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
            "additionalProperties": False,
        },
        handler=lambda expression: f"resultat:{expression}",
    )
    return reg


def call(name: str = "calc_evaluate", **arguments: str) -> LLMResponse:
    return LLMResponse(text="", tool_calls=[ToolCall(name=name, arguments=arguments)])


def test_tool_call_then_answer(registry: ToolRegistry) -> None:
    provider = ScriptedProvider(
        script=[call(expression="2+2"), LLMResponse(text="La somme vaut 4.")]
    )
    agent = Lab(provider, registry=registry)
    answer, steps = asyncio.run(agent.run_loop("combien font 2+2 ?"))
    assert answer == "La somme vaut 4."
    assert steps == 2
    # l'observation de l'outil a bien ete reinjectee dans le contexte
    tool_messages = [m for m in provider.calls[1] if m.role == "tool"]
    assert tool_messages and "resultat:2+2" in tool_messages[0].content
    assert tool_messages[0].tool_call_id


def test_parallel_tool_calls_in_one_step(registry: ToolRegistry) -> None:
    provider = ScriptedProvider(
        script=[
            LLMResponse(
                text="",
                tool_calls=[
                    ToolCall(name="calc_evaluate", arguments={"expression": "1+1"}),
                    ToolCall(name="calc_evaluate", arguments={"expression": "2+2"}),
                ],
            ),
            LLMResponse(text="fini"),
        ]
    )
    agent = Lab(provider, registry=registry)
    asyncio.run(agent.run_loop("deux calculs"))
    observations = [m.content for m in provider.calls[1] if m.role == "tool"]
    assert observations == ["resultat:1+1", "resultat:2+2"]


def test_max_steps_forces_final_answer(registry: ToolRegistry) -> None:
    provider = ScriptedProvider(
        script=[call(expression="1+1"), call(expression="1+1"), LLMResponse(text="reponse finale")]
    )
    agent = Lab(provider, registry=registry)
    answer, steps = asyncio.run(agent.run_loop("boucle", max_steps=2))
    assert answer == "reponse finale"
    assert steps == 3  # 2 etapes + finalisation forcee
    assert provider.calls[-1][-1].content.startswith("Limite d'etapes atteinte")


def test_unknown_tool_is_reported_to_the_model(registry: ToolRegistry) -> None:
    provider = ScriptedProvider(
        script=[call(name="rm_rf", path="/"), LLMResponse(text="je corrige")]
    )
    agent = Lab(provider, registry=registry)
    asyncio.run(agent.run_loop("test"))
    observation = next(m for m in provider.calls[1] if m.role == "tool")
    assert "ERREUR" in observation.content


def test_tool_not_allowed_is_refused(registry: ToolRegistry) -> None:
    provider = ScriptedProvider(script=[call(expression="1+1"), LLMResponse(text="ok")])
    agent = Lab(provider, registry=registry)
    asyncio.run(agent.run_loop("test", allowed=["file_read"]))
    observation = next(m for m in provider.calls[1] if m.role == "tool")
    assert "pas autorise" in observation.content


def test_unknown_argument_is_reported_not_raised(registry: ToolRegistry) -> None:
    provider = ScriptedProvider(
        script=[call(expression="1+1", injection="--rm"), LLMResponse(text="ok")]
    )
    agent = Lab(provider, registry=registry)
    asyncio.run(agent.run_loop("test"))
    observation = next(m for m in provider.calls[1] if m.role == "tool")
    assert "ERREUR" in observation.content and "inconnus" in observation.content


def test_missing_argument_is_reported(registry: ToolRegistry) -> None:
    provider = ScriptedProvider(script=[call(autre="x"), LLMResponse(text="ok")])
    agent = Lab(provider, registry=registry)
    asyncio.run(agent.run_loop("test"))
    observation = next(m for m in provider.calls[1] if m.role == "tool")
    assert "manquants" in observation.content


def test_agent_without_registry(registry: ToolRegistry) -> None:
    provider = ScriptedProvider(script=[call(expression="1"), LLMResponse(text="ok")])
    agent = Lab(provider, registry=None)
    asyncio.run(agent.run_loop("test"))
    observation = next(m for m in provider.calls[1] if m.role == "tool")
    assert "aucun outil" in observation.content


def test_budget_stops_the_loop(registry: ToolRegistry) -> None:
    provider = ScriptedProvider(
        script=[call(expression="1"), call(expression="2"), LLMResponse(text="jamais")]
    )
    budget = Budget(max_llm_calls=1)
    agent = Lab(provider, registry=registry, budget=budget)
    with pytest.raises(BudgetExceeded):
        asyncio.run(agent.run_loop("test", max_steps=3))
    assert budget.usage.llm_calls == 1


def test_events_are_emitted(registry: ToolRegistry) -> None:
    sink = CollectorSink()
    provider = ScriptedProvider(script=[call(expression="1+1"), LLMResponse(text="ok")])
    agent = Lab(provider, registry=registry, bus=EventBus([sink]))
    asyncio.run(agent.run_loop("test"))
    kinds = sink.kinds()
    assert "llm.request" in kinds and "tool.call" in kinds and "tool.result" in kinds
    assert all("run_id" in event and "ts" in event for event in sink.events)


def test_invalid_max_steps_rejected(registry: ToolRegistry) -> None:
    with pytest.raises(ValueError, match="max_steps"):
        Lab(ScriptedProvider(script=[]), registry=registry, max_steps=0)
