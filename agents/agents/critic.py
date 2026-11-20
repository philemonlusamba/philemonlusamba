"""Critique : note chaque resultat et decide s'il doit etre revise.

Le critique est un garde-fou qualite, pas un juge infaillible : en cas de sortie
inexploitable il retombe sur une heuristique, et le score est toujours borne a
[0, 1] pour que l'orchestrateur ne prenne pas de decision sur une valeur absurde.
"""

from __future__ import annotations

from typing import Any

from agents.agents.base import Agent
from agents.core.jsonio import as_float, as_str_list, extract_json_object
from agents.core.models import Message, Review, Task, TaskResult

ACCEPT_THRESHOLD = 0.7
REVISE_THRESHOLD = 0.4


class Critic(Agent):
    """Evalue la qualite d'un resultat de tache."""

    role = "critic"
    SYSTEM_PROMPT = """Tu es le CRITIC d'un orchestrateur multi-agents.

Tu evalues un resultat de tache au regard de son instruction.

Tu refuses : un resultat vide, hors sujet, trop vague, ou qui affirme un chiffre
ou une source sans appui visible.

Reponds UNIQUEMENT avec un objet JSON, sans texte autour :
{"score": 0.0, "verdict": "accept", "issues": ["probleme constate"]}
- score : nombre entre 0 et 1
- verdict : "accept" (>= 0.7), "revise" (0.4 a 0.69) ou "reject" (< 0.4)
- issues : liste courte de problemes concrets (vide si accepte)"""

    def __init__(self, provider: Any, **kwargs: Any) -> None:
        kwargs.setdefault("max_steps", 1)
        super().__init__(provider, **kwargs)

    async def review(self, task: Task, result: TaskResult, *, objective: str) -> Review:
        """Note un resultat ; ne leve jamais, retourne une heuristique en cas d'echec."""
        if not result.ok:
            review = Review(
                task_id=task.id,
                score=0.0,
                verdict="reject",
                issues=(result.error or "tache en echec",),
            )
            self.bus.emit("review.done", task_id=task.id, score=0.0, verdict="reject")
            return review

        messages = [
            Message(role="system", content=self.system_prompt()),
            Message(role="user", content=self._user_prompt(task, result, objective)),
        ]
        try:
            response = await self._complete(messages, None, metadata={"task_id": task.id})
            review = parse_review(task.id, response.text)
        except Exception as exc:
            self.bus.emit("review.fallback", task_id=task.id, error=f"{type(exc).__name__}")
            review = heuristic_review(task.id, result)
        self.bus.emit(
            "review.done", task_id=task.id, score=round(review.score, 2), verdict=review.verdict
        )
        return review

    @staticmethod
    def _user_prompt(task: Task, result: TaskResult, objective: str) -> str:
        return (
            f"[[OBJECTIF]]\n{objective}\n\n"
            f"[[TACHE]]\n{task.id} — {task.title}\n\n"
            f"[[INSTRUCTION]]\n{task.instruction}\n\n"
            f"[[RESULTAT]]\n{result.output[:2500]}\n\n"
            "Renvoie ton evaluation JSON."
        )


def parse_review(task_id: str, text: str) -> Review:
    """Analyse le JSON du critique et borne les valeurs."""
    data = extract_json_object(text)
    score = max(0.0, min(1.0, as_float(data.get("score"), 0.5)))
    raw_verdict = str(data.get("verdict", "")).strip().lower()
    if raw_verdict not in {"accept", "revise", "reject"}:
        raw_verdict = _verdict_for(score)
    issues = tuple(as_str_list(data.get("issues")))
    return Review(task_id=task_id, score=score, verdict=raw_verdict, issues=issues)  # type: ignore[arg-type]


def heuristic_review(task_id: str, result: TaskResult) -> Review:
    """Avis de repli, purement factuel, utilise si le LLM repond mal."""
    output = result.output.strip()
    if not output:
        return Review(task_id, 0.0, "reject", ("resultat vide",))
    score = 0.75 if len(output) >= 80 else 0.55
    issues: list[str] = [] if len(output) >= 80 else ("resultat tres court",)
    return Review(task_id, score, _verdict_for(score), issues)


def _verdict_for(score: float) -> str:
    if score >= ACCEPT_THRESHOLD:
        return "accept"
    if score >= REVISE_THRESHOLD:
        return "revise"
    return "reject"
