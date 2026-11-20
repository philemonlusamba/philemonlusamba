"""Provider factice, deterministe et hors ligne.

Objectif double :

* rendre le projet **executable sans cle API** (demo, CI, relecture du code) ;
* rendre les tests **reproductibles** : meme entree => meme sortie, sans latence.

Il ne cherche pas a imiter un LLM, mais a jouer le role de chacun (planner,
worker, critic, synthesizer) de facon lisible. Le role est fourni par
``metadata["agent_role"]`` et, a defaut, deduit du prompt systeme.

Convention de dialogue : les prompts structurent le contexte en sections
delimitees ``[[NOM_DE_SECTION]]``. C'est ce qui permet au mock d'extraire
l'objectif, l'instruction ou le resultat sans heuristique fragile sur du texte
libre — et cela reste parfaitement lisible pour un vrai modele.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from agents.core.llm import ToolSchema, estimate_tokens
from agents.core.models import LLMResponse, Message, ToolCall, Usage

_MATH_CHARS_RE = re.compile(r"^[\d\s.+\-*/%^()]+$")
_MULTIPLY_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:x|\u00d7|\*|fois)\s*(\d+(?:[.,]\d+)?)", re.I)
_SECTION_RE = re.compile(r"\[\[([A-Z_]+)\]\]")
_ROLE_MARKERS = ("SYNTHESIZER", "CRITIC", "PLANNER", "WORKER")
_ANGLES = (
    "verifier d'abord la definition exacte des termes avant de conclure",
    "privilégier la source primaire plutot qu'une reformulation de seconde main",
    "chiffrer l'ordre de grandeur avant d'entrer dans le detail",
    "distinguer ce qui est mesure de ce qui est estime",
    "chercher le contre-exemple qui invaliderait la these",
)

_TOOL_NOISE = {
    "outil",
    "outils",
    "appelle",
    "appeler",
    "requete",
    "suivante",
    "doc_search",
    "calc_evaluate",
    "passages",
    "retiens",
    "utiles",
    "trouve",
    "suivants",
}

_STOPWORDS = {
    "le",
    "la",
    "les",
    "un",
    "une",
    "des",
    "du",
    "de",
    "dans",
    "sur",
    "pour",
    "avec",
    "et",
    "ou",
    "en",
    "au",
    "aux",
    "ce",
    "cette",
    "ces",
    "il",
    "elle",
    "on",
    "nous",
    "vous",
    "ils",
    "que",
    "qui",
    "quel",
    "quelle",
    "est",
    "sont",
    "a",
    "par",
    "plus",
    "the",
    "an",
    "of",
    "to",
    "in",
    "and",
    "or",
    "for",
    "with",
    "is",
    "are",
}


class MockProvider:
    """Provider hors ligne deterministe."""

    def __init__(self, *, model: str = "mock-1", delay_s: float = 0.0) -> None:
        self.name = "mock"
        self.model = model
        self.delay_s = delay_s
        self.calls: list[list[Message]] = []

    # ------------------------------------------------------------------ API
    async def complete(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[ToolSchema] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 800,
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMResponse:
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        self.calls.append(list(messages))
        role = self._resolve_role(messages, metadata)
        tool_names = [str(schema.get("name", "")) for schema in (tools or [])]

        tool_calls: list[ToolCall] = []
        member = str((metadata or {}).get("member", "membre"))
        round_number = int((metadata or {}).get("round", 1) or 1)
        if role == "council_member":
            text = self._council_member(messages, member, round_number)
        elif role == "council_judge":
            text = self._council_judge(messages)
        elif role == "planner":
            text = self._plan(messages, tool_names)
        elif role == "critic":
            text = self._review(messages)
        elif role == "synthesizer":
            text = self._synthesize(messages)
        elif role == "worker":
            text, tool_calls = self._work(messages, tool_names)
        else:
            text = (
                "Reponse du provider mock : aucun appel de modele reel n'a ete effectue. "
                "Utilisez --provider openai:... ou --provider anthropic:... pour un vrai modele."
            )

        prompt_tokens = estimate_tokens("\n".join(message.content for message in messages))
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=estimate_tokens(text),
                llm_calls=1,
            ),
            provider=self.name,
            model=self.model,
            finish_reason="tool_calls" if tool_calls else "stop",
        )

    # ------------------------------------------------------------- interne
    def _resolve_role(self, messages: Sequence[Message], metadata: Mapping[str, Any] | None) -> str:
        if metadata:
            role = str(metadata.get("agent_role", "")).lower()
            if role:
                return role
        system = " ".join(m.content.upper() for m in messages if m.role == "system")
        for marker in _ROLE_MARKERS:
            if marker in system:
                return marker.lower()
        return "assistant"

    @staticmethod
    def _last(messages: Sequence[Message], role: str) -> str:
        for message in reversed(messages):
            if message.role == role:
                return message.content
        return ""

    @staticmethod
    def _section(text: str, key: str) -> str:
        """Contenu de la section ``[[KEY]]`` jusqu'au prochain marqueur ``[[...]]``."""
        pattern = re.compile(rf"\[\[{re.escape(key)}\]\]\s*(.*?)(?=\[\[[A-Z_]+\]\]|\Z)", re.S)
        match = pattern.search(text)
        return match.group(1).strip() if match else ""

    def _tool_outputs(self, messages: Sequence[Message]) -> list[str]:
        return [message.content for message in messages if message.role == "tool"]

    # --------------------------------------------------------------- roles
    def _plan(self, messages: Sequence[Message], tool_names: list[str]) -> str:
        prompt = self._last(messages, "user")
        objective = self._section(prompt, "OBJECTIF") or prompt
        objective = " ".join(objective.split())[:400]

        # Le planner recoit les outils dans le prompt (pas en tool-calling) :
        # on lit la section [[OUTILS]] en plus des schemas eventuels.
        declared = re.findall(r"-\s*([a-z_][a-z0-9_]*)", self._section(prompt, "OUTILS"))
        tool_names = list(dict.fromkeys([*tool_names, *declared]))

        expressions = self._expressions(objective)
        query = self._keywords(objective) or objective[:80]
        tasks: list[dict[str, Any]] = []

        if expressions and "calc_evaluate" in tool_names:
            tasks.append(
                {
                    "id": f"t{len(tasks) + 1}",
                    "title": "Calcul",
                    "instruction": (
                        "Appelle l'outil calc_evaluate sur l'expression "
                        f"{expressions[0]} et donne le resultat exact."
                    ),
                    "depends_on": [],
                    "max_steps": 3,
                    "tools": ["calc_evaluate"],
                }
            )

        tasks.append(
            {
                "id": f"t{len(tasks) + 1}",
                "title": "Recherche documentaire",
                "instruction": f"Recherche documentaire sur le sujet: {query}",
                "depends_on": [],
                "max_steps": 3,
                "tools": ["doc_search"] if "doc_search" in tool_names else [],
            }
        )
        dependencies = [task["id"] for task in tasks]
        tasks.append(
            {
                "id": f"t{len(tasks) + 1}",
                "title": "Redaction",
                "instruction": (
                    "Redige une reponse concise et structuree a l'objectif, en reprenant "
                    "les elements obtenus par les taches precedentes."
                ),
                "depends_on": dependencies,
                "max_steps": 2,
                "tools": [],
            }
        )
        return json.dumps({"tasks": tasks}, ensure_ascii=False)

    def _work(
        self, messages: Sequence[Message], tool_names: list[str]
    ) -> tuple[str, list[ToolCall]]:
        prompt = self._last(messages, "user")
        instruction = self._section(prompt, "INSTRUCTION") or prompt
        tool_outputs = self._tool_outputs(messages)

        if tool_outputs:
            joined = "\n".join(output.strip() for output in tool_outputs if output.strip())
            return (
                "Resultat obtenu via outil(s):\n"
                + joined[:900]
                + "\n\nConclusion: donnee collectee et verifiee, prete pour la synthese.",
                [],
            )

        dependencies = self._section(prompt, "DEPENDANCES")
        if dependencies:
            # Tache de consolidation : on reprend les sorties amont sans nouvel outil.
            return (
                "Synthese des elements amont :\n"
                + dependencies[:1000]
                + "\n\nProposition: reponse consolidee a partir des resultats ci-dessus.",
                [],
            )

        already_called = {
            message.name for message in messages if message.role == "tool" and message.name
        }
        expressions = self._expressions(instruction)
        if "calc_evaluate" in tool_names and "calc_evaluate" not in already_called and expressions:
            return "", [ToolCall(name="calc_evaluate", arguments={"expression": expressions[0]})]

        if "doc_search" in tool_names and "doc_search" not in already_called:
            query = self._keywords(instruction) or instruction[:80]
            return "", [ToolCall(name="doc_search", arguments={"query": query, "top_k": 3})]

        return (
            "Analyse de l'etape:\n"
            f"- instruction: {instruction[:200]}\n"
            "- aucune donnee externe necessaire : traitement direct du contexte fourni.\n"
            "Proposition: reponse structuree, prete a etre evaluee par le critique.",
            [],
        )

    def _review(self, messages: Sequence[Message]) -> str:
        prompt = self._last(messages, "user")
        body = self._section(prompt, "RESULTAT") or prompt
        empty = len(body.strip()) < 40 or "ERREUR" in body.upper()
        payload = (
            {"score": 0.2, "verdict": "reject", "issues": ["resultat vide ou en erreur"]}
            if empty
            else {"score": 0.86, "verdict": "accept", "issues": []}
        )
        return json.dumps(payload, ensure_ascii=False)

    def _synthesize(self, messages: Sequence[Message]) -> str:
        prompt = self._last(messages, "user")
        objective = " ".join((self._section(prompt, "OBJECTIF") or "l'objectif").split())[:300]
        blocks = re.findall(
            r"^###\s+(\w+)\s+—\s+(.+?)\s+\(score\s+([\d.]+)\)\s*$([\s\S]*?)(?=^###\s|\Z)",
            self._section(prompt, "RESULTATS"),
            re.M,
        )
        lines = ["## Reponse", "", f"Objectif traite : {objective}", ""]
        if not blocks:
            lines.append(
                "Aucun resultat de tache exploitable n'a ete fourni ; la synthese se limite "
                "a l'objectif initial."
            )
            return "\n".join(lines)
        for task_id, title, score, content in blocks:
            cleaned = " ".join(content.split())
            lines.append(f"**{task_id} — {title}** (confiance {score})")
            lines.append("")
            lines.append(cleaned[:400] or "_resultat vide_")
            lines.append("")
        lines.append(
            f"_{len(blocks)} tache(s) agregee(s). Reponse produite hors ligne par le provider "
            "mock : brancher un modele reel via --provider pour une qualite superieure._"
        )
        return "\n".join(lines)

    def _council_member(self, messages: Sequence[Message], label: str, round_number: int) -> str:
        """Proposition ou revision d'un membre du conseil (mock)."""
        prompt = self._last(messages, "user")
        question = " ".join((self._section(prompt, "QUESTION") or prompt).split())[:220]
        keywords = self._keywords(question)[:90] or "elements disponibles"
        angle = _ANGLES[int(hashlib.sha256(label.encode()).hexdigest(), 16) % len(_ANGLES)]

        if round_number >= 2 and self._section(prompt, "REPONSES ANONYMES"):
            return (
                f"[{label}] Revision apres lecture croisee.\n"
                "- Les reponses anonymes ne contredisent pas mon analyse sur le fond.\n"
                f"- Point renforce : {keywords}.\n"
                f"- Reservation maintenue : {angle}\n"
                "Reponse revisee: conclusion confirmee, avec la reserve explicite ci-dessus."
            )
        return (
            f"[{label}] Reponse directe : traiter la demande en isolant les faits verifiables "
            f"({keywords}).\n"
            f"- Analyse : {angle}\n"
            "- Verification : toute donnee chiffree doit etre confirmee par un "
            "outil ou une source.\n"
            "- Incertitude : le perimetre exact de la question n'est pas entierement specifie."
        )

    def _council_judge(self, messages: Sequence[Message]) -> str:
        """Synthese du juge (mock) : consensus, divergences, reponse, confiance."""
        prompt = self._last(messages, "user")
        question = " ".join((self._section(prompt, "QUESTION") or "question").split())[:200]
        contributions = self._section(prompt, "CONTRIBUTIONS")
        labels = re.findall(r"^### (.+)$", contributions, re.M) or ["membre unique"]
        extracted = [
            " ".join(block.split())[:180]
            for block in re.split(r"^### .+$", contributions, flags=re.M)
            if block.strip()
        ]
        body = "\n".join(
            f"- **{label}** : {text}" for label, text in zip(labels, extracted, strict=False)
        )
        return (
            "## Consensus\n"
            f"- Les {len(labels)} membres ({', '.join(labels)}) traitent bien la question posée : "
            f"{question}\n"
            "- Accord sur la methode : repondre d'abord, verifier ensuite.\n\n"
            "## Divergences\n"
            "- Aucune divergence majeure : les sorties proviennent du provider mock "
            "(simulation hors ligne), donc volontairement proches.\n\n"
            "## Reponse finale\n"
            f"{body}\n\n"
            "## Confiance\n"
            "moyen — deliberation hors ligne avec le provider mock ; brancher les vraies API "
            "(--provider) pour une reponse de production."
        )

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _expressions(text: str) -> list[str]:
        found: list[str] = []
        for left, right in _MULTIPLY_RE.findall(text):
            found.append(f"{left.replace(',', '.')}*{right.replace(',', '.')}")
        for match in re.finditer(r"[\d\s.+\-*/%^()]{5,}", text):
            candidate = match.group(0).strip(" .")
            if not any(char.isdigit() for char in candidate):
                continue
            if not any(op in candidate for op in "+-*/%^"):
                continue
            if not _MATH_CHARS_RE.match(candidate) or candidate.count("(") != candidate.count(")"):
                continue
            found.append(candidate)
        return found

    @staticmethod
    def _keywords(text: str) -> str:
        words = re.findall(r"[\w'À-ÿ]+", text.lower())
        kept = [
            word
            for word in words
            if len(word) > 2 and word not in _STOPWORDS and word not in _TOOL_NOISE
        ]
        return " ".join(dict.fromkeys(kept))[:120]
