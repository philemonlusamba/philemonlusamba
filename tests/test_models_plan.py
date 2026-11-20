"""Tests des modeles et de la validation de plan (DAG)."""

from __future__ import annotations

import json

import pytest
from agents.core.errors import PlanningError
from agents.core.models import Plan, Review, Task, TaskResult, Usage


def make(task_id: str, deps: tuple[str, ...] = ()) -> Task:
    return Task(id=task_id, title=task_id, instruction=f"faire {task_id}", depends_on=deps)


def test_usage_addition_and_merge() -> None:
    total = Usage(1, 2, 1) + Usage(3, 4, 1)
    assert total == Usage(4, 6, 2)
    assert total.total_tokens == 10
    assert Usage.merge([Usage(1, 1, 1), Usage(2, 2, 2)]).total_tokens == 6


def test_valid_plan_batches() -> None:
    plan = Plan(
        objective="o",
        tasks=(make("t1"), make("t2"), make("t3", ("t1", "t2"))),
    )
    plan.validate()
    batches = plan.topological_batches()
    assert [[task.id for task in batch] for batch in batches] == [["t1", "t2"], ["t3"]]


def test_empty_plan_is_refused() -> None:
    with pytest.raises(PlanningError, match="aucune tache"):
        Plan(objective="o", tasks=()).validate()


def test_duplicate_ids_refused() -> None:
    with pytest.raises(PlanningError, match="duplique"):
        Plan(objective="o", tasks=(make("t1"), make("t1"))).validate()


def test_missing_dependency_refused() -> None:
    with pytest.raises(PlanningError, match="inconnu"):
        Plan(objective="o", tasks=(make("t1", ("t9",)),)).validate()


def test_self_dependency_refused() -> None:
    with pytest.raises(PlanningError, match="elle-meme"):
        Plan(objective="o", tasks=(make("t1", ("t1",)),)).validate()


def test_cycle_detected() -> None:
    plan = Plan(objective="o", tasks=(make("t1", ("t2",)), make("t2", ("t1",))))
    with pytest.raises(PlanningError, match="cycle"):
        plan.validate()


def test_empty_instruction_refused() -> None:
    plan = Plan(objective="o", tasks=(Task(id="t1", title="t", instruction="  "),))
    with pytest.raises(PlanningError, match="instruction"):
        plan.validate()


def test_empty_id_refused() -> None:
    plan = Plan(objective="o", tasks=(Task(id="", title="t", instruction="x"),))
    with pytest.raises(PlanningError, match="identifiant vide"):
        plan.validate()


def test_report_is_json_serializable() -> None:
    plan = Plan(objective="o", tasks=(make("t1"),))
    result = TaskResult(
        task_id="t1",
        status="succeeded",
        output="ok",
        usage=Usage(1, 2, 1),
        review=Review(task_id="t1", score=0.9, verdict="accept", issues=()),
    )
    from agents.core.models import RunReport

    report = RunReport(
        run_id="r1",
        objective="o",
        plan=plan,
        results=[result],
        final_answer="fini",
        usage=Usage(1, 2, 1),
        duration_ms=12.0,
        provider="mock",
        status="succeeded",
    )
    payload = json.loads(json.dumps(report.to_dict(), ensure_ascii=False))
    assert payload["results"][0]["review"]["verdict"] == "accept"
    assert payload["plan"]["tasks"][0]["id"] == "t1"
    assert report.succeeded == [result]
    assert report.failures == []


def test_task_result_ok_property() -> None:
    assert TaskResult(task_id="t", status="succeeded").ok
    assert not TaskResult(task_id="t", status="blocked").ok
    assert not TaskResult(task_id="t", status="timeout").ok
