"""Tests de l'orchestrateur : parallelisme, isolation des pannes, budget, revisions.

Les agents sont remplaces par des doubles deterministes : ces tests portent sur
l'ordonnancement et la gestion d'erreurs, pas sur la qualite d'un modele.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from agents.core.budget import Budget
from agents.core.bus import CollectorSink, EventBus
from agents.core.errors import AgentError, BudgetExceeded
from agents.core.models import Plan, Review, Task, TaskResult
from agents.core.providers.mock import MockProvider
from agents.orchestrator import Orchestrator, RunConfig


class FixedPlanner:
    def __init__(self, plan: Plan) -> None:
        self._plan = plan
        self.budget = None

    async def plan(self, objective: str, *, available_tools=None) -> Plan:
        return self._plan


class RecordingWorker:
    """Worker configurable : latence, echecs cibles, compteur de concurrence."""

    def __init__(
        self,
        *,
        delay: float = 0.0,
        fail_ids: tuple[str, ...] = (),
        fail_once: tuple[str, ...] = (),
        raise_budget: bool = False,
    ) -> None:
        self.delay = delay
        self.fail_ids = set(fail_ids)
        self.fail_once = set(fail_once)
        self.raise_budget = raise_budget
        self.active = 0
        self.peak = 0
        self.calls: list[str] = []
        self.budget = None

    async def execute(self, task, *, objective, dependency_outputs=None) -> TaskResult:
        self.calls.append(task.id)
        if self.raise_budget:
            raise BudgetExceeded("quota de test epuise")
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
        finally:
            self.active -= 1
        if task.id in self.fail_ids:
            return TaskResult(task_id=task.id, status="failed", error="echec simule")
        if task.id in self.fail_once:
            self.fail_once.discard(task.id)
            return TaskResult(task_id=task.id, status="failed", error="echec transitoire")
        return TaskResult(task_id=task.id, status="succeeded", output=f"sortie {task.id}")


class FixedCritic:
    def __init__(self, score: float = 0.9, verdict: str = "accept", scores=None) -> None:
        self.score = score
        self.verdict = verdict
        self.scores = list(scores or [])
        self.calls: list[str] = []
        self.budget = None

    async def review(self, task, result, *, objective) -> Review:
        self.calls.append(result.task_id)
        score = self.scores.pop(0) if self.scores else self.score
        verdict = self.verdict if not self.scores else ("accept" if score >= 0.7 else "revise")
        return Review(task_id=result.task_id, score=score, verdict=verdict)


class FixedSynthesizer:
    def __init__(self, answer: str = "reponse finale") -> None:
        self.answer = answer
        self.budget = None

    async def synthesize(self, objective, tasks, results, *, rejected=()) -> str:
        return self.answer


def plan_of(*tasks: Task, objective: str = "objectif") -> Plan:
    return Plan(objective=objective, tasks=tuple(tasks), source="test")


def task(task_id: str, deps: tuple[str, ...] = ()) -> Task:
    return Task(id=task_id, title=task_id, instruction=f"faire {task_id}", depends_on=deps)


def build(
    plan: Plan, worker=None, critic=None, synthesizer=None, config=None, budget=None, bus=None
):
    return Orchestrator(
        provider=MockProvider(),
        registry=None,
        config=config or RunConfig(),
        budget=budget,
        bus=bus,
        planner=FixedPlanner(plan),
        worker=worker or RecordingWorker(),
        critic=critic or FixedCritic(),
        synthesizer=synthesizer or FixedSynthesizer(),
    )


# ----------------------------------------------------------------- heureux
def test_happy_path() -> None:
    plan = plan_of(task("t1"), task("t2"), task("t3", ("t1", "t2")))
    synth = FixedSynthesizer("reponse finale")
    report = asyncio.run(build(plan, synthesizer=synth).run("objectif"))
    assert report.status == "succeeded"
    assert [result.task_id for result in report.results] == ["t1", "t2", "t3"]
    assert all(result.ok for result in report.results)
    assert report.final_answer == "reponse finale"
    assert report.duration_ms >= 0
    assert report.plan.source == "test"


def test_report_is_json_serializable() -> None:
    plan = plan_of(task("t1"))
    report = asyncio.run(build(plan).run("objectif"))
    payload = json.loads(json.dumps(report.to_dict(), ensure_ascii=False))
    assert payload["status"] == "succeeded"
    assert payload["results"][0]["status"] == "succeeded"


# ------------------------------------------------------------ parallelisme
def test_independent_tasks_run_in_parallel() -> None:
    plan = plan_of(*[task(f"t{i}") for i in range(1, 5)])
    worker = RecordingWorker(delay=0.1)
    started = time.perf_counter()
    asyncio.run(build(plan, worker=worker, config=RunConfig(concurrency=4)).run("o"))
    elapsed = time.perf_counter() - started
    assert worker.peak == 4  # les quatre taches ont bien tourne ensemble
    assert elapsed < 0.32, f"trop lent pour du parallelisme: {elapsed:.2f}s"


def test_concurrency_one_is_sequential() -> None:
    plan = plan_of(*[task(f"t{i}") for i in range(1, 4)])
    worker = RecordingWorker(delay=0.05)
    started = time.perf_counter()
    asyncio.run(build(plan, worker=worker, config=RunConfig(concurrency=1)).run("o"))
    elapsed = time.perf_counter() - started
    assert worker.peak == 1
    assert elapsed >= 0.14


def test_dependency_chain_does_not_deadlock() -> None:
    plan = plan_of(task("t1"), task("t2", ("t1",)), task("t3", ("t2",)), task("t4", ("t3",)))
    report = asyncio.run(
        build(plan, worker=RecordingWorker(delay=0.01), config=RunConfig(concurrency=1)).run("o")
    )
    assert report.status == "succeeded"
    assert len(report.results) == 4


# --------------------------------------------------------------- pannes
def test_failure_blocks_dependents_only() -> None:
    plan = plan_of(task("t1"), task("t2", ("t1",)), task("t3"))
    report = asyncio.run(build(plan, worker=RecordingWorker(fail_ids=("t1",))).run("o"))
    statuses = {result.task_id: result.status for result in report.results}
    assert statuses == {"t1": "failed", "t2": "blocked", "t3": "succeeded"}
    assert report.status == "partial"


def test_retry_then_success() -> None:
    plan = plan_of(task("t1"))
    worker = RecordingWorker(fail_once=("t1",))
    report = asyncio.run(build(plan, worker=worker, config=RunConfig(max_attempts=2)).run("o"))
    assert report.status == "succeeded"
    assert report.results[0].attempts == 2
    assert worker.calls == ["t1", "t1"]


def test_task_timeout_is_recorded() -> None:
    plan = plan_of(task("t1"))
    worker = RecordingWorker(delay=0.3)
    config = RunConfig(task_timeout_s=0.05, max_attempts=1)
    report = asyncio.run(build(plan, worker=worker, config=config).run("o"))
    assert report.results[0].status == "timeout"
    assert report.status == "failed"


def test_budget_exhaustion_produces_partial_report() -> None:
    plan = plan_of(task("t1"), task("t2"))
    worker = RecordingWorker(raise_budget=True)
    report = asyncio.run(build(plan, worker=worker).run("o"))
    assert report.status == "failed"
    assert any("budget" in error for error in report.errors)
    assert report.final_answer  # une synthese de repli est toujours produite


def test_budget_limits_llm_calls_end_to_end(registry) -> None:
    orchestrator = Orchestrator(
        provider=MockProvider(),
        registry=registry,
        config=RunConfig(concurrency=2),
        budget=Budget(max_llm_calls=2),
    )
    report = asyncio.run(orchestrator.run("Combien coutent 12 x 249,99 USD ?"))
    assert report.status in {"failed", "partial"}
    assert any("budget" in error for error in report.errors)


# -------------------------------------------------------------- revisions
def test_revision_improves_result() -> None:
    plan = plan_of(task("t1"))
    critic = FixedCritic(scores=[0.4, 0.95])
    report = asyncio.run(build(plan, critic=critic).run("o"))
    assert report.results[0].review is not None
    assert report.results[0].review.score == 0.95
    assert len(critic.calls) == 2


def test_revision_is_reverted_when_worse() -> None:
    plan = plan_of(task("t1"))
    critic = FixedCritic(scores=[0.5, 0.2])
    report = asyncio.run(build(plan, critic=critic).run("o"))
    assert report.results[0].review is not None
    assert report.results[0].review.score == 0.5


def test_no_revision_when_disabled() -> None:
    plan = plan_of(task("t1"))
    critic = FixedCritic(scores=[0.2])
    report = asyncio.run(build(plan, critic=critic, config=RunConfig(max_revisions=0)).run("o"))
    assert len(critic.calls) == 1
    assert report.results[0].review is not None


def test_rejected_results_are_reported_explicitly() -> None:
    plan = plan_of(task("t1"))
    critic = FixedCritic(score=0.1, verdict="reject")
    report = asyncio.run(build(plan, critic=critic, config=RunConfig(max_revisions=0)).run("o"))
    assert report.status == "partial"


# ------------------------------------------------------------- validation
def test_empty_objective_rejected() -> None:
    with pytest.raises(AgentError, match="vide"):
        asyncio.run(build(plan_of(task("t1"))).run("   "))


def test_too_long_objective_rejected() -> None:
    with pytest.raises(AgentError, match="trop long"):
        asyncio.run(build(plan_of(task("t1"))).run("a" * 2001))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"concurrency": 0},
        {"task_timeout_s": 0},
        {"run_timeout_s": -1},
        {"max_attempts": 0},
        {"max_revisions": -1},
    ],
)
def test_run_config_validation(kwargs) -> None:
    with pytest.raises(ValueError):
        RunConfig(**kwargs)


# ------------------------------------------------------------ integration
def test_end_to_end_with_mock_provider(registry) -> None:
    bus_sink = CollectorSink()
    orchestrator = Orchestrator(
        provider=MockProvider(),
        registry=registry,
        bus=EventBus([bus_sink], run_id="it"),
        config=RunConfig(concurrency=3),
    )
    report = asyncio.run(orchestrator.run("Combien coutent 12 x 249,99 USD ?"))
    assert report.status == "succeeded"
    assert len(report.results) == 3
    assert "Reponse" in report.final_answer
    assert "2999.88" in report.final_answer
    kinds = bus_sink.kinds()
    assert kinds[0] == "run.start"
    assert kinds[-1] == "run.end"
    assert kinds.count("task.start") >= 3


def test_failing_sink_does_not_break_run(registry) -> None:
    class BrokenSink:
        def emit(self, event) -> None:
            raise RuntimeError("disque plein")

    bus = EventBus([BrokenSink(), CollectorSink()], run_id="x")
    orchestrator = Orchestrator(provider=MockProvider(), registry=registry, bus=bus)
    report = asyncio.run(orchestrator.run("Combien coutent 12 x 249,99 USD ?"))
    assert report.status == "succeeded"


# --------------------------------------------------- robustesse du planning
def test_invalid_plan_from_custom_planner_is_rejected() -> None:
    from agents.core.errors import PlanningError

    cyclic = Plan(
        objective="o",
        tasks=(task("t1", ("t2",)), task("t2", ("t1",))),
        source="test",
    )
    orchestrator = build(cyclic)
    with pytest.raises(PlanningError, match="cycle"):
        asyncio.run(orchestrator.run("objectif"))


def test_max_steps_option_caps_task_budget() -> None:
    captured: list[int] = []

    class StepRecorder(RecordingWorker):
        async def execute(self, task, *, objective, dependency_outputs=None):
            captured.append(task.max_steps)
            return await super().execute(
                task, objective=objective, dependency_outputs=dependency_outputs
            )

    plan = Plan(
        objective="o",
        tasks=(Task(id="t1", title="t", instruction="i", max_steps=5),),
        source="test",
    )
    asyncio.run(build(plan, worker=StepRecorder(), config=RunConfig(max_steps=2)).run("o"))
    assert captured == [2]


def test_timeout_global_produces_partial_report() -> None:
    plan = plan_of(task("t1"))
    worker = RecordingWorker(delay=0.3)
    config = RunConfig(task_timeout_s=10, run_timeout_s=0.05, max_attempts=1)
    report = asyncio.run(build(plan, worker=worker, config=config).run("o"))
    assert report.results[0].status == "timeout"
    assert any("duree maximale" in error for error in report.errors)
