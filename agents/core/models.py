"""Modeles de donnees immuables partages par tout le framework.

Tout est serialisable en JSON (``to_dict``) pour que ``--json``, les traces JSONL
et les tests partagent le meme format.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

from agents.core.errors import PlanningError

Role = Literal["system", "user", "assistant", "tool"]
TaskStatus = Literal["pending", "running", "succeeded", "failed", "blocked", "timeout"]
Verdict = Literal["accept", "revise", "reject"]


@dataclass(frozen=True, slots=True)
class Usage:
    """Consommation cumulee (tokens et nombre d'appels LLM)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: Usage) -> Usage:
        if not isinstance(other, Usage):
            return NotImplemented
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            llm_calls=self.llm_calls + other.llm_calls,
        )

    @classmethod
    def merge(cls, items: list[Usage] | tuple[Usage, ...]) -> Usage:
        total = cls()
        for item in items:
            total = total + item
        return total

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "llm_calls": self.llm_calls,
        }


@dataclass(frozen=True, slots=True)
class ToolCall:
    """Demande d'execution d'outil emise par le modele.

    ``id`` est renseigne par l'agent avant execution : les APIs OpenAI/Anthropic
    exigent que le message de resultat d'outil reference l'identifiant exact de
    l'appel (sinon 400 en mode reel).
    """

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    id: str = ""

    def with_id(self, call_id: str) -> ToolCall:
        return ToolCall(name=self.name, arguments=self.arguments, id=call_id)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "arguments": self.arguments}


@dataclass(frozen=True, slots=True)
class Message:
    """Message d'une conversation, au format commun a tous les providers."""

    role: Role
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name is not None:
            payload["name"] = self.name
        if self.tool_call_id is not None:
            payload["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            payload["tool_calls"] = [call.to_dict() for call in self.tool_calls]
        return payload


@dataclass(slots=True)
class LLMResponse:
    """Reponse normalisee d'un provider LLM."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    provider: str = "unknown"
    model: str = ""
    finish_reason: str = "stop"
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "tool_calls": [call.to_dict() for call in self.tool_calls],
            "usage": self.usage.to_dict(),
            "provider": self.provider,
            "model": self.model,
            "finish_reason": self.finish_reason,
        }


@dataclass(frozen=True, slots=True)
class Task:
    """Une unite de travail du plan, executable en parallele de ses soeurs."""

    id: str
    title: str
    instruction: str
    depends_on: tuple[str, ...] = ()
    max_steps: int = 4
    tools: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "instruction": self.instruction,
            "depends_on": list(self.depends_on),
            "max_steps": self.max_steps,
            "tools": list(self.tools),
        }


@dataclass(frozen=True, slots=True)
class Plan:
    """Graphe acyclique oriente de taches."""

    objective: str
    tasks: tuple[Task, ...]
    source: str = "llm"

    def validate(self) -> None:
        """Verifie identifiants, dependances et absence de cycle.

        Leve :class:`PlanningError` avec un message precis : un plan invalide ne
        doit jamais provoquer un blocage silencieux de l'orchestrateur.
        """
        if not self.tasks:
            raise PlanningError("le plan ne contient aucune tache")
        seen: set[str] = set()
        for task in self.tasks:
            if not task.id:
                raise PlanningError("une tache a un identifiant vide")
            if task.id in seen:
                raise PlanningError(
                    f"identifiant de tache duplique: {task.id!r}",
                    hint="le planner doit produire des identifiants uniques",
                )
            if not task.instruction.strip():
                raise PlanningError(
                    f"la tache {task.id!r} n'a pas d'instruction",
                    hint="chaque tache doit decrire une action concrete",
                )
            seen.add(task.id)

        for task in self.tasks:
            if task.id in task.depends_on:
                raise PlanningError(f"la tache {task.id!r} depend d'elle-meme")
            for dep in task.depends_on:
                if dep not in seen:
                    raise PlanningError(
                        f"la tache {task.id!r} depend d'un identifiant inconnu: {dep!r}",
                        hint="les dependances doivent referencer des taches du meme plan",
                    )
        self.topological_batches()  # leve en cas de cycle

    def topological_batches(self) -> list[list[Task]]:
        """Regroupe les taches par niveau : toutes celles d'un lot sont independantes."""
        remaining = {task.id: set(task.depends_on) for task in self.tasks}
        by_id = {task.id: task for task in self.tasks}
        batches: list[list[Task]] = []
        resolved: set[str] = set()

        while remaining:
            ready = [tid for tid, deps in remaining.items() if deps <= resolved]
            if not ready:
                cycle = ", ".join(sorted(remaining))
                raise PlanningError(
                    f"cycle de dependances detecte entre: {cycle}",
                    hint="un plan doit etre un DAG (pas de boucle)",
                )
            ready.sort()
            batches.append([by_id[tid] for tid in ready])
            resolved.update(ready)
            for tid in ready:
                del remaining[tid]
        return batches

    def by_id(self) -> dict[str, Task]:
        return {task.id: task for task in self.tasks}

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "source": self.source,
            "tasks": [task.to_dict() for task in self.tasks],
        }


@dataclass(frozen=True, slots=True)
class Review:
    """Avis du critique sur le resultat d'une tache."""

    task_id: str
    score: float
    verdict: Verdict
    issues: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "score": round(self.score, 3),
            "verdict": self.verdict,
            "issues": list(self.issues),
        }


@dataclass(slots=True)
class TaskResult:
    """Resultat d'execution d'une tache, y compris ses echecs."""

    task_id: str
    status: TaskStatus
    output: str = ""
    error: str | None = None
    attempts: int = 0
    steps: int = 0
    duration_ms: float = 0.0
    usage: Usage = field(default_factory=Usage)
    review: Review | None = None

    @property
    def ok(self) -> bool:
        return self.status == "succeeded"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "attempts": self.attempts,
            "steps": self.steps,
            "duration_ms": round(self.duration_ms, 1),
            "usage": self.usage.to_dict(),
            "review": self.review.to_dict() if self.review else None,
        }


@dataclass(slots=True)
class RunReport:
    """Compte rendu complet d'un run : plan, resultats, cout, reponse finale."""

    run_id: str
    objective: str
    plan: Plan
    results: list[TaskResult]
    final_answer: str
    usage: Usage
    duration_ms: float
    provider: str
    status: Literal["succeeded", "partial", "failed"] = "succeeded"
    errors: list[str] = field(default_factory=list)

    @property
    def failures(self) -> list[TaskResult]:
        return [result for result in self.results if not result.ok]

    @property
    def succeeded(self) -> list[TaskResult]:
        return [result for result in self.results if result.ok]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "objective": self.objective,
            "status": self.status,
            "provider": self.provider,
            "duration_ms": round(self.duration_ms, 1),
            "usage": self.usage.to_dict(),
            "errors": list(self.errors),
            "plan": self.plan.to_dict(),
            "results": [result.to_dict() for result in self.results],
            "final_answer": self.final_answer,
        }


def utc_now_iso() -> str:
    """Horodatage ISO 8601 en UTC (stable pour les traces et les tests)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
