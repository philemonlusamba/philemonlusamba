"""Worker : execute une tache unique, avec ses outils autorises.

Un worker ne voit que : l'objectif global, sa propre instruction et les sorties
des taches dont il depend. Cette isolation evite que le contexte de toutes les
taches ne sature le modele et rend le parallelisme sur.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence

from agents.agents.base import Agent
from agents.core.errors import BudgetExceeded
from agents.core.models import Message, Task, TaskResult

MAX_DEPENDENCY_CHARS = 1200


class Worker(Agent):
    """Execute une tache et retourne un :class:`TaskResult`."""

    role = "worker"
    SYSTEM_PROMPT = """Tu es le WORKER d'un orchestrateur multi-agents.

Tu executes UNE tache precise, avec les outils mis a ta disposition.

Regles :
- appelle un outil des qu'un chiffre exact ou une source documentaire est
  necessaire : ne calcule pas de tete, ne cite pas de memoire ;
- n'invente jamais un chiffre, un nom de fichier ou une citation ;
- si une information manque et qu'aucun outil ne peut la fournir, dis-le
  explicitement au lieu de combler le vide ;
- reponds en 5 lignes maximum, en francais, sans preambule ni formule de politesse."""

    async def execute(
        self,
        task: Task,
        *,
        objective: str,
        dependency_outputs: Mapping[str, str] | None = None,
        allowed_tools: Sequence[str] | None = None,
    ) -> TaskResult:
        """Execute la tache ; les erreurs sont capturees dans le resultat."""
        started = time.perf_counter()
        messages = [
            Message(role="system", content=self.system_prompt()),
            Message(role="user", content=self._user_prompt(task, objective, dependency_outputs)),
        ]
        allowed = list(task.tools) if task.tools else list(allowed_tools or [])
        try:
            text, steps, usage = await self.react(
                messages,
                allowed_tools=allowed or None,
                max_steps=task.max_steps,
                task_id=task.id,
            )
        except BudgetExceeded:
            raise  # le budget est global : l'orchestrateur doit interrompre le run
        except Exception as exc:
            return TaskResult(
                task_id=task.id,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=(time.perf_counter() - started) * 1000,
            )

        duration_ms = (time.perf_counter() - started) * 1000
        if not text.strip():
            return TaskResult(
                task_id=task.id,
                status="failed",
                error="le worker n'a produit aucun texte",
                steps=steps,
                duration_ms=duration_ms,
                usage=usage,
            )
        return TaskResult(
            task_id=task.id,
            status="succeeded",
            output=text.strip(),
            steps=steps,
            duration_ms=duration_ms,
            usage=usage,
        )

    @staticmethod
    def _user_prompt(
        task: Task,
        objective: str,
        dependency_outputs: Mapping[str, str] | None,
    ) -> str:
        sections = [
            f"[[OBJECTIF]]\n{objective}",
            f"[[TACHE]]\n{task.id} — {task.title}",
            f"[[INSTRUCTION]]\n{task.instruction}",
        ]
        if dependency_outputs:
            blocks = [
                f"[{dep_id}] {output[:MAX_DEPENDENCY_CHARS]}"
                for dep_id, output in dependency_outputs.items()
            ]
            sections.append("[[DEPENDANCES]]\n" + "\n\n".join(blocks))
        sections.append("[[CONSIGNE]]\nExecute la tache et reponds directement.")
        return "\n\n".join(sections)
