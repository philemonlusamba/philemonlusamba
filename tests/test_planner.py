"""Tests du planner : JSON valide, reparation, repli heuristique, normalisation."""

from __future__ import annotations

import asyncio
import json

import pytest
from agents.agents.planner import Planner, heuristic_plan, parse_plan
from agents.core.errors import PlanningError
from agents.core.models import LLMResponse
from agents.core.providers.mock import MockProvider
from agents.core.providers.scripted import ScriptedProvider

VALID = json.dumps(
    {
        "tasks": [
            {
                "id": "t1",
                "title": "Calcul",
                "instruction": "calculer 2+2",
                "tools": ["calc_evaluate"],
            },
            {"id": "t2", "title": "Redaction", "instruction": "rediger", "depends_on": ["t1"]},
        ]
    }
)


def test_valid_llm_plan() -> None:
    planner = Planner(ScriptedProvider(script=[LLMResponse(text=VALID)]))
    plan = asyncio.run(planner.plan("objectif", available_tools=["calc_evaluate", "doc_search"]))
    assert plan.source == "llm"
    assert [task.id for task in plan.tasks] == ["t1", "t2"]
    assert plan.tasks[0].tools == ("calc_evaluate",)
    plan.validate()


def test_invalid_json_then_repaired() -> None:
    provider = ScriptedProvider(
        script=[LLMResponse(text="desole je ne peux pas"), LLMResponse(text=VALID)]
    )
    planner = Planner(provider)
    plan = asyncio.run(planner.plan("objectif"))
    assert plan.source == "llm"
    assert provider.remaining == 0
    assert "JSON precedent est invalide" in provider.calls[1][-1].content


def test_two_failures_fall_back_to_heuristic() -> None:
    provider = ScriptedProvider(
        script=[LLMResponse(text="nope"), LLMResponse(text="toujours nope")]
    )
    planner = Planner(provider)
    plan = asyncio.run(planner.plan("objectif", available_tools=["doc_search"]))
    assert plan.source == "fallback"
    assert len(plan.tasks) == 3
    plan.validate()


def test_cycle_in_llm_plan_falls_back() -> None:
    cyclic = json.dumps(
        {
            "tasks": [
                {"id": "t1", "title": "a", "instruction": "a", "depends_on": ["t2"]},
                {"id": "t2", "title": "b", "instruction": "b", "depends_on": ["t1"]},
            ]
        }
    )
    planner = Planner(ScriptedProvider(script=[LLMResponse(text=cyclic), LLMResponse(text=cyclic)]))
    plan = asyncio.run(planner.plan("objectif"))
    assert plan.source == "fallback"


def test_parse_plan_normalises_fields() -> None:
    data = {
        "tasks": [
            "juste une chaine",
            {
                "id": "tâche 2",
                "instruction": "faire X",
                "max_steps": 99,
                "tools": ["outil_inconnu", "calc_evaluate"],
            },
            {"id": "t3", "title": "sans instruction"},
        ]
    }
    plan = parse_plan("obj", data, available_tools=["calc_evaluate"])
    assert plan.tasks[0].id == "t1"
    assert plan.tasks[0].instruction == "juste une chaine"
    assert plan.tasks[1].max_steps == 5  # borne haute
    assert plan.tasks[1].tools == ("calc_evaluate",)  # outil inconnu filtre
    with pytest.raises(PlanningError, match="instruction"):
        plan.validate()


def test_parse_plan_rejects_empty_payloads() -> None:
    with pytest.raises(PlanningError):
        parse_plan("obj", {"tasks": []})
    with pytest.raises(PlanningError):
        parse_plan("obj", {"autre": 1})


def test_plan_is_capped() -> None:
    data = {"tasks": [{"id": f"t{i}", "instruction": f"i{i}"} for i in range(12)]}
    plan = parse_plan("obj", data, max_tasks=4)
    assert len(plan.tasks) == 4


def test_heuristic_plan_is_valid_and_deterministic() -> None:
    first = heuristic_plan("objectif", available_tools=["doc_search"])
    second = heuristic_plan("objectif", available_tools=["doc_search"])
    assert first.to_dict() == second.to_dict()
    first.validate()
    assert first.tasks[0].tools == ("doc_search",)


def test_mock_planner_produces_valid_plan() -> None:
    planner = Planner(MockProvider())
    plan = asyncio.run(
        planner.plan(
            "Combien coutent 12 x 249,99 USD ?", available_tools=["calc_evaluate", "doc_search"]
        )
    )
    plan.validate()
    assert plan.source == "llm"
    assert len(plan.tasks) == 3
    assert plan.tasks[0].title == "Calcul"
    assert plan.tasks[2].depends_on == ("t1", "t2")
