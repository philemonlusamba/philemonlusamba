"""Planner : transforme un objectif en DAG de taches.

Robustesse recherchee : un modele qui renvoie du JSON casse, des dependances
inconnues ou un cycle ne doit **jamais** faire planter le run. On tente une
reecriture, puis on retombe sur un plan heuristique deterministe et annote
(``Plan.source == "fallback"``), visible dans le rapport.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agents.agents.base import Agent
from agents.core.errors import PlanningError
from agents.core.jsonio import as_int, as_str_list, extract_json_object
from agents.core.models import Message, Plan, Task

MAX_TASKS = 6
MAX_STEPS_PER_TASK = 5


class Planner(Agent):
    """Decompose l'objectif utilisateur en taches executables."""

    role = "planner"
    SYSTEM_PROMPT = """Tu es le PLANNER d'un orchestrateur multi-agents.

Ta mission : decomposer un objectif en 2 a 4 taches concretes, executables en
parallele quand elles sont independantes.

Regles strictes :
- chaque tache a un identifiant court et unique : t1, t2, t3...
- "depends_on" ne cite que des identifiants presents dans le meme plan ;
- le graphe doit etre un DAG : aucun cycle, aucune tache ne depend d'elle-meme ;
- les taches independantes seront lancees en parallele : n'ajoute pas de
  dependance inutile ;
- une tache qui a besoin d'une donnee doit nommer l'outil a utiliser dans son
  instruction (par exemple "utilise doc_search pour ...") ;
- "max_steps" entre 1 et 4.

Reponds UNIQUEMENT avec un objet JSON, sans texte autour, au format :
{"tasks": [{"id": "t1", "title": "titre court", "instruction": "action precise",
            "depends_on": [], "max_steps": 3, "tools": ["doc_search"]}]}"""

    def __init__(self, provider: Any, **kwargs: Any) -> None:
        kwargs.setdefault("max_steps", 1)
        super().__init__(provider, **kwargs)

    async def plan(
        self,
        objective: str,
        *,
        available_tools: Sequence[str] | None = None,
        max_tasks: int = MAX_TASKS,
    ) -> Plan:
        """Produit un plan valide, avec deux tentatives puis repli heuristique."""
        tool_list = list(available_tools or [])
        messages = [
            Message(role="system", content=self.system_prompt()),
            Message(role="user", content=self._user_prompt(objective, tool_list)),
        ]
        errors: list[str] = []

        for attempt in (1, 2):
            response = await self._complete(messages, None, metadata={"attempt": attempt})
            try:
                plan = parse_plan(
                    objective,
                    extract_json_object(response.text),
                    available_tools=tool_list,
                    max_tasks=max_tasks,
                    source="llm",
                )
                plan.validate()
            except (ValueError, PlanningError) as exc:
                errors.append(str(exc))
                self.bus.emit("plan.invalid", attempt=attempt, error=str(exc)[:300])
                if attempt == 1:
                    messages.append(Message(role="assistant", content=response.text))
                    messages.append(Message(role="user", content=self._repair_prompt(str(exc))))
                continue
            self.bus.emit("plan.created", source="llm", tasks=len(plan.tasks), attempt=attempt)
            return plan

        plan = heuristic_plan(objective, available_tools=tool_list)
        self.bus.emit(
            "plan.created",
            source="fallback",
            tasks=len(plan.tasks),
            error=errors[-1][:300] if errors else "sortie LLM inexploitable",
        )
        return plan

    @staticmethod
    def _user_prompt(objective: str, tool_list: Sequence[str]) -> str:
        tools = "\n".join(f"- {name}" for name in tool_list) or "- aucun outil disponible"
        return (
            f"[[OBJECTIF]]\n{objective}\n\n[[OUTILS]]\n{tools}\n\nProduis le plan JSON maintenant."
        )

    @staticmethod
    def _repair_prompt(error: str) -> str:
        return (
            f"Ton JSON precedent est invalide : {error}\n"
            "Renvoie uniquement un objet JSON valide conforme au schema "
            '{"tasks": [...]}, sans commentaire ni balise.'
        )


def parse_plan(
    objective: str,
    data: dict[str, Any],
    *,
    available_tools: Sequence[str] | None = None,
    max_tasks: int = MAX_TASKS,
    source: str = "llm",
) -> Plan:
    """Normalise un objet JSON en :class:`Plan` (leve :class:`PlanningError` sinon)."""
    raw_tasks = data.get("tasks") or data.get("plan") or data.get("steps")
    if isinstance(raw_tasks, dict):
        raw_tasks = raw_tasks.get("tasks")
    if not isinstance(raw_tasks, (list, tuple)) or not raw_tasks:
        raise PlanningError(
            "le JSON du planner ne contient pas de liste 'tasks' exploitable",
            hint='format attendu: {"tasks": [{"id": "t1", ...}]}',
        )

    allowed_tools = set(available_tools or [])
    tasks: list[Task] = []
    for index, raw in enumerate(raw_tasks[:max_tasks], start=1):
        if isinstance(raw, str):
            tasks.append(Task(id=f"t{index}", title=raw[:60], instruction=raw, max_steps=3))
            continue
        if not isinstance(raw, dict):
            raise PlanningError(f"tache #{index} invalide: {type(raw).__name__}")

        task_id = str(raw.get("id") or raw.get("task_id") or f"t{index}").strip()
        instruction = str(
            raw.get("instruction") or raw.get("task") or raw.get("description") or ""
        ).strip()
        title = str(raw.get("title") or raw.get("name") or instruction[:60]).strip()
        declared = as_str_list(raw.get("tools"))
        tools = tuple(name for name in declared if not allowed_tools or name in allowed_tools)
        tasks.append(
            Task(
                id=task_id,
                title=title or task_id,
                instruction=instruction,
                depends_on=tuple(as_str_list(raw.get("depends_on") or raw.get("deps"))),
                max_steps=max(1, min(MAX_STEPS_PER_TASK, as_int(raw.get("max_steps"), 3))),
                tools=tools,
            )
        )

    if not tasks:
        raise PlanningError("aucune tache exploitable dans le plan")
    return Plan(objective=objective, tasks=tuple(tasks), source=source)


def heuristic_plan(objective: str, *, available_tools: Sequence[str] | None = None) -> Plan:
    """Plan de repli deterministe, utilise si le LLM ne produit pas de JSON valide."""
    tools = set(available_tools or [])
    analysis_tools = tuple(name for name in ("doc_search",) if name in tools)
    tasks: list[Task] = [
        Task(
            id="t1",
            title="Collecte d'informations",
            instruction=(
                "Rassemble les elements verifiables necessaires a l'objectif, en utilisant "
                f"doc_search si disponible. Objectif: {objective}"
            ),
            max_steps=3,
            tools=analysis_tools,
        ),
        Task(
            id="t2",
            title="Traitement",
            instruction=(
                "Traite les elements collectes en t1 et produis une reponse structuree "
                f"a l'objectif: {objective}"
            ),
            depends_on=("t1",),
            max_steps=2,
        ),
        Task(
            id="t3",
            title="Verification",
            instruction=(
                "Verifie la coherence de la reponse de t2 (chiffres, sources, absence "
                "d'affirmation non etayee) et corrige ce qui doit l'etre."
            ),
            depends_on=("t2",),
            max_steps=2,
        ),
    ]
    return Plan(objective=objective, tasks=tuple(tasks), source="fallback")
