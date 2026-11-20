"""Synthetiseur : compose la reponse finale a partir des resultats acceptes.

Il cite les identifiants de taches (t1, t2...) pour que l'utilisateur puisse
remonter a la source de chaque affirmation, et signale explicitement les echecs
au lieu de les masquer.
"""

from __future__ import annotations

from collections.abc import Sequence

from agents.agents.base import Agent
from agents.core.models import Message, Task, TaskResult

MAX_BLOCK_CHARS = 1200


class Synthesizer(Agent):
    """Produit une reponse finale structuree et tracable."""

    role = "synthesizer"
    SYSTEM_PROMPT = """Tu es le SYNTHESIZER d'un orchestrateur multi-agents.

Tu composes LA reponse finale a l'objectif de l'utilisateur a partir des
resultats de taches, deja evalues par un critique.

Regles :
- structure Markdown courte : une phrase de reponse, puis les points cles ;
- cite les taches entre parentheses, par exemple (t1), pour chaque fait ;
- n'ajoute aucun fait absent des resultats fournis ;
- si une tache a echoue ou a ete rejetee, dis-le explicitement en fin de reponse ;
- termine par une phrase d'action concrete si pertinent ;
- pas de formule d'introduction du type "voici la synthese"."""

    async def synthesize(
        self,
        objective: str,
        tasks: Sequence[Task],
        results: Sequence[TaskResult],
        *,
        rejected: Sequence[str] = (),
    ) -> str:
        """Compose la reponse finale ; un repli deterministe garantit un texte non vide."""
        messages = [
            Message(role="system", content=self.system_prompt()),
            Message(role="user", content=self._user_prompt(objective, tasks, results, rejected)),
        ]
        try:
            response = await self._complete(messages, None, metadata={})
            answer = response.text.strip()
        except Exception as exc:
            self.bus.emit("synthesis.fallback", error=f"{type(exc).__name__}: {exc}"[:200])
            answer = ""
        if not answer:
            answer = fallback_answer(objective, tasks, results, rejected)
            self.bus.emit("synthesis.fallback", reason="reponse vide")
        return answer

    @staticmethod
    def _user_prompt(
        objective: str,
        tasks: Sequence[Task],
        results: Sequence[TaskResult],
        rejected: Sequence[str],
    ) -> str:
        titles = {task.id: task.title for task in tasks}
        by_id = {result.task_id: result for result in results}
        blocks: list[str] = []
        for task in tasks:
            result = by_id.get(task.id)
            if result is None or not result.ok:
                continue
            score = f"{result.review.score:.2f}" if result.review else "n/a"
            blocks.append(
                f"### {task.id} — {titles.get(task.id, task.id)} (score {score})\n"
                f"{result.output[:MAX_BLOCK_CHARS]}"
            )
        if not blocks:
            blocks.append("### aucune — aucun resultat exploitable (score 0.00)\naucun resultat")
        failed = [
            f"- {result.task_id}: {result.error or result.status}"
            for result in results
            if not result.ok
        ]
        if rejected:
            failed.append(f"- rejetes par le critique: {', '.join(sorted(set(rejected)))}")

        return (
            f"[[OBJECTIF]]\n{objective}\n\n"
            "[[RESULTATS]]\n"
            + "\n\n".join(blocks)
            + "\n\n"
            + ("[[ECHECS]]\n" + "\n".join(failed) + "\n\n" if failed else "")
            + "Redige la reponse finale en francais."
        )


def fallback_answer(
    objective: str,
    tasks: Sequence[Task],
    results: Sequence[TaskResult],
    rejected: Sequence[str] = (),
) -> str:
    """Reponse de secours assemblee sans LLM (jamais vide, toujours honnete)."""
    lines = ["## Reponse", "", f"Objectif traite : {objective}", ""]
    for result in results:
        if not result.ok:
            continue
        score = f"{result.review.score:.2f}" if result.review else "n/a"
        lines.append(f"**{result.task_id}** (confiance {score})")
        lines.append("")
        lines.append(" ".join(result.output.split())[:400])
        lines.append("")
    failures = [result.task_id for result in results if not result.ok]
    if failures or rejected:
        details = ", ".join(sorted(set(failures) | set(rejected)))
        lines.append(f"_Taches sans resultat exploitable : {details}._")
    lines.append(
        f"_{len(tasks)} tache(s) planifiee(s), {sum(1 for r in results if r.ok)} reussie(s). "
        "Synthese produite sans modele (repli)."
    )
    return "\n".join(lines)
