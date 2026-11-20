"""Orchestrateur : plan -> workers paralleles -> critique -> revisions -> synthese.

Points de conception qui comptent :

* **parallelisme reel** : chaque tache est une ``asyncio.Task`` qui attend ses
  dependances via un ``Event``, puis prend un jeton de semaphore. L'attente des
  dependances se fait *avant* le semaphore : sinon un plan en chaine
  s'auto-bloquerait (interblocage classique des pools de threads).
* **panne isolee** : une tache en echec marque ses dependantes ``blocked`` sans
  empecher les autres branches du DAG d'aboutir.
* **degradation gracieuse** : budget epuise ou duree depassee produisent un
  rapport partiel exploitable, jamais une exception nue devant l'utilisateur.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace

from agents.agents.critic import Critic, heuristic_review
from agents.agents.planner import Planner
from agents.agents.synthesizer import Synthesizer, fallback_answer
from agents.agents.worker import Worker
from agents.core.budget import Budget
from agents.core.bus import EventBus, NullSink
from agents.core.errors import AgentError, BudgetExceeded
from agents.core.llm import LLMProvider
from agents.core.models import Plan, RunReport, Task, TaskResult
from agents.core.registry import ToolRegistry


@dataclass(frozen=True, slots=True)
class RunConfig:
    """Reglages d'execution, exposes en CLI."""

    concurrency: int = 3
    task_timeout_s: float = 45.0
    run_timeout_s: float = 300.0
    max_attempts: int = 2
    retry_backoff_s: float = 0.15
    revise_below: float = 0.7
    max_revisions: int = 1
    max_steps: int | None = None

    def __post_init__(self) -> None:
        if self.concurrency < 1:
            raise ValueError("concurrency doit etre >= 1")
        if self.task_timeout_s <= 0 or self.run_timeout_s <= 0:
            raise ValueError("les timeouts doivent etre > 0")
        if self.max_attempts < 1:
            raise ValueError("max_attempts doit etre >= 1")
        if self.max_revisions < 0:
            raise ValueError("max_revisions doit etre >= 0")


class Orchestrator:
    """Chef d'orchestre du pipeline multi-agents."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        registry: ToolRegistry | None = None,
        config: RunConfig | None = None,
        budget: Budget | None = None,
        bus: EventBus | None = None,
        planner: Planner | None = None,
        worker: Worker | None = None,
        critic: Critic | None = None,
        synthesizer: Synthesizer | None = None,
    ) -> None:
        self.provider = provider
        self.registry = registry or ToolRegistry()
        self.config = config or RunConfig()
        self._fixed_budget = budget
        self.bus = bus or EventBus([NullSink()])
        self.planner = planner or Planner(provider, registry=self.registry, bus=self.bus)
        self.worker = worker or Worker(provider, registry=self.registry, bus=self.bus)
        self.critic = critic or Critic(provider, bus=self.bus)
        self.synthesizer = synthesizer or Synthesizer(provider, bus=self.bus)

    # ------------------------------------------------------------------ API
    async def run(self, objective: str) -> RunReport:
        """Execute le pipeline complet et retourne un rapport exploitable."""
        cleaned = " ".join(objective.split())
        if not cleaned:
            raise AgentError("objectif vide", hint="passer un objectif en argument")
        if len(cleaned) > 2000:
            raise AgentError(
                "objectif trop long (> 2000 caracteres)",
                hint="resumer l'objectif ou le decouper en plusieurs runs",
            )

        run_id = uuid.uuid4().hex[:12]
        budget = self._fixed_budget or Budget()
        started_at = time.perf_counter()
        self._bind_budget(budget)
        self.bus.emit("run.start", objective=cleaned[:200], concurrency=self.config.concurrency)

        plan = await self.planner.plan(cleaned, available_tools=self.registry.names())
        plan.validate()  # un planner personnalise peut renvoyer un DAG invalide
        results, errors = await self._execute_plan(plan, budget)
        await self._review_results(plan, results)
        results = await self._revise_results(plan, results)
        rejected = [
            result.task_id
            for result in results
            if result.review is not None and result.review.verdict == "reject"
        ]
        final_answer = await self._synthesize(plan, results, rejected)

        succeeded = [result for result in results if result.ok]
        if not succeeded:
            status = "failed"
        elif len(succeeded) == len(results) and not rejected:
            status = "succeeded"
        else:
            status = "partial"

        report = RunReport(
            run_id=run_id,
            objective=cleaned,
            plan=plan,
            results=sorted(results, key=lambda item: item.task_id),
            final_answer=final_answer,
            usage=budget.usage,
            duration_ms=(time.perf_counter() - started_at) * 1000,
            provider=getattr(self.provider, "name", "unknown"),
            status=status,
            errors=errors,
        )
        self.bus.emit(
            "run.end",
            status=status,
            tasks=len(results),
            ok=len(succeeded),
            tokens=budget.usage.total_tokens,
            duration_ms=round(report.duration_ms, 1),
        )
        return report

    def run_sync(self, objective: str) -> RunReport:
        """Variante synchrone (CLI, notebooks)."""
        return asyncio.run(self.run(objective))

    # ------------------------------------------------------------ execution
    def _bind_budget(self, budget: Budget) -> None:
        """Injecte le budget du run dans tous les agents, y compris ceux fournis."""
        self.planner.budget = budget
        self.worker.budget = budget
        self.critic.budget = budget
        self.synthesizer.budget = budget

    async def _execute_plan(self, plan: Plan, budget: Budget) -> tuple[list[TaskResult], list[str]]:
        events = {task.id: asyncio.Event() for task in plan.tasks}
        results: dict[str, TaskResult] = {}
        errors: list[str] = []
        semaphore = asyncio.Semaphore(self.config.concurrency)
        aborted = asyncio.Event()

        async def run_one(task: Task) -> None:
            try:
                for dependency in task.depends_on:
                    await events[dependency].wait()
                blocked = [
                    dep for dep in task.depends_on if dep not in results or not results[dep].ok
                ]
                if aborted.is_set():
                    results[task.id] = TaskResult(
                        task_id=task.id, status="blocked", error="run interrompu (budget)"
                    )
                    return
                if blocked:
                    results[task.id] = TaskResult(
                        task_id=task.id,
                        status="blocked",
                        error=f"dependances non satisfaites: {', '.join(blocked)}",
                    )
                    return
                async with semaphore:
                    if aborted.is_set():
                        results[task.id] = TaskResult(
                            task_id=task.id, status="blocked", error="run interrompu (budget)"
                        )
                        return
                    try:
                        results[task.id] = await self._execute_task(task, plan.objective, results)
                    except BudgetExceeded as exc:
                        aborted.set()
                        errors.append(f"budget epuise: {exc}")
                        self.bus.emit("budget.exceeded", error=str(exc)[:200])
                        results[task.id] = TaskResult(
                            task_id=task.id,
                            status="failed",
                            error=f"budget epuise: {exc}",
                        )
            finally:
                events[task.id].set()

        runners = [asyncio.create_task(run_one(task)) for task in plan.tasks]
        try:
            await asyncio.wait_for(
                asyncio.gather(*runners, return_exceptions=True),
                timeout=self.config.run_timeout_s,
            )
        except TimeoutError:
            errors.append(f"duree maximale du run depassee ({self.config.run_timeout_s:.0f}s)")
            self.bus.emit("run.timeout", seconds=self.config.run_timeout_s)
            for runner in runners:
                runner.cancel()
            await asyncio.gather(*runners, return_exceptions=True)

        for task in plan.tasks:  # filet de securite : tout plan aboutit a un resultat
            results.setdefault(
                task.id,
                TaskResult(
                    task_id=task.id,
                    status="timeout" if errors else "failed",
                    error="aucun resultat produit",
                ),
            )
        return [results[task.id] for task in plan.tasks], errors

    async def _execute_task(
        self,
        task: Task,
        objective: str,
        results: dict[str, TaskResult],
    ) -> TaskResult:
        """Execute une tache, avec retries sur echec technique uniquement."""
        dependency_outputs = {
            dep: results[dep].output
            for dep in task.depends_on
            if dep in results and results[dep].ok
        }
        if self.config.max_steps is not None:
            task = replace(task, max_steps=max(1, min(task.max_steps, self.config.max_steps)))
        last: TaskResult | None = None
        for attempt in range(1, self.config.max_attempts + 1):
            self.bus.emit("task.start", task_id=task.id, title=task.title, attempt=attempt)
            try:
                result = await asyncio.wait_for(
                    self.worker.execute(
                        task,
                        objective=objective,
                        dependency_outputs=dependency_outputs,
                    ),
                    timeout=self.config.task_timeout_s,
                )
            except TimeoutError:
                self.bus.emit("task.timeout", task_id=task.id, attempt=attempt)
                result = TaskResult(
                    task_id=task.id,
                    status="timeout",
                    error=f"timeout de la tache ({self.config.task_timeout_s:.0f}s)",
                )
            except BudgetExceeded:
                raise  # le budget est global : on interrompt le run
            except Exception as exc:
                self.bus.emit("task.error", task_id=task.id, error=str(exc)[:200])
                result = TaskResult(
                    task_id=task.id,
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
            result.attempts = attempt
            last = result
            if result.ok:
                self.bus.emit(
                    "task.end",
                    task_id=task.id,
                    status=result.status,
                    steps=result.steps,
                    chars=len(result.output),
                )
                return result
            self.bus.emit(
                "task.retry" if attempt < self.config.max_attempts else "task.end",
                task_id=task.id,
                status=result.status,
                error=(result.error or "")[:200],
            )
            if attempt < self.config.max_attempts:
                await asyncio.sleep(self.config.retry_backoff_s * attempt)
        assert last is not None
        return last

    # -------------------------------------------------------------- qualite
    async def _review_results(self, plan: Plan, results: Sequence[TaskResult]) -> None:
        """Evalue chaque resultat en parallele ; une panne du critique n'est pas bloquante."""
        semaphore = asyncio.Semaphore(self.config.concurrency)
        by_id = plan.by_id()

        async def review_one(result: TaskResult) -> None:
            task = by_id.get(result.task_id)
            if task is None:
                return
            if not result.ok:
                result.review = heuristic_review(result.task_id, result)
                return
            async with semaphore:
                try:
                    result.review = await asyncio.wait_for(
                        self.critic.review(task, result, objective=plan.objective),
                        timeout=self.config.task_timeout_s,
                    )
                except (TimeoutError, BudgetExceeded) as exc:
                    self.bus.emit("review.fallback", task_id=result.task_id, reason=str(exc)[:120])
                    result.review = heuristic_review(result.task_id, result)
                except Exception as exc:
                    self.bus.emit("review.error", task_id=result.task_id, error=str(exc)[:200])
                    result.review = heuristic_review(result.task_id, result)

        await asyncio.gather(*(review_one(result) for result in results))

    async def _revise_results(self, plan: Plan, results: list[TaskResult]) -> list[TaskResult]:
        """Relance au plus une fois les taches jugees insuffisantes, critiques en main."""
        if self.config.max_revisions < 1:
            return results
        by_id = plan.by_id()
        revised: list[TaskResult] = []
        for result in results:
            review = result.review
            needs_revision = (
                review is not None
                and result.ok
                and review.verdict != "accept"
                and review.score < self.config.revise_below
                and result.task_id in by_id
            )
            if not needs_revision or review is None:
                revised.append(result)
                continue
            feedback = "; ".join(review.issues) or "qualite insuffisante"
            self.bus.emit("task.revise", task_id=result.task_id, score=round(review.score, 2))
            revised.append(
                await self._revise_one(by_id[result.task_id], result, feedback, plan.objective)
            )
        return revised

    async def _revise_one(
        self,
        task: Task,
        previous: TaskResult,
        feedback: str,
        objective: str,
    ) -> TaskResult:
        revised_task = Task(
            id=task.id,
            title=task.title,
            instruction=(
                f"{task.instruction}\n\n"
                f"Correction demandee par le critique : {feedback}. "
                "Ameliore le resultat precedent en corrigeant precisement ces points."
            ),
            depends_on=task.depends_on,
            max_steps=task.max_steps,
            tools=task.tools,
        )
        try:
            candidate = await asyncio.wait_for(
                self.worker.execute(revised_task, objective=objective),
                timeout=self.config.task_timeout_s,
            )
            if not candidate.ok:
                return previous
            candidate.review = await self.critic.review(
                revised_task, candidate, objective=objective
            )
        except BudgetExceeded:
            self.bus.emit("task.revise.skipped", task_id=task.id, reason="budget epuise")
            return previous
        except Exception as exc:
            self.bus.emit("task.revise.failed", task_id=task.id, error=str(exc)[:200])
            return previous

        if candidate.review and previous.review and candidate.review.score < previous.review.score:
            self.bus.emit("task.revise.reverted", task_id=task.id)
            return previous  # la revision degrade : on garde l'original
        candidate.attempts = previous.attempts
        self.bus.emit(
            "task.revised",
            task_id=task.id,
            score=round(candidate.review.score, 2) if candidate.review else None,
        )
        return candidate

    async def _synthesize(
        self, plan: Plan, results: Sequence[TaskResult], rejected: Sequence[str]
    ) -> str:
        try:
            answer = await asyncio.wait_for(
                self.synthesizer.synthesize(plan.objective, plan.tasks, results, rejected=rejected),
                timeout=self.config.task_timeout_s,
            )
        except Exception as exc:
            self.bus.emit("synthesis.error", error=str(exc)[:300])
            answer = ""
        return answer or fallback_answer(plan.objective, plan.tasks, results, rejected)
