"""Conseil multi-modeles : plusieurs IA deliberent, puis un juge synthetise.

Motivation : un seul modele a un angle mort, et il ne le voit pas. Ici trois
modeles **differents** (par exemple ChatGPT, Claude et Gemini) repondent en
parallele, puis se critiquent mutuellement sur des reponses **anonymisees**
(evite le suivisme et l'ancrage sur le modele le plus bavard), et enfin un juge
produit la reponse finale en exposant consensus et divergences.

Le module ne depend d'aucun fournisseur en particulier : il ne manipule que le
protocole :class:`~agents.core.llm.LLMProvider`. C'est ce qui permet de le faire
tourner hors ligne avec trois ``mock``, puis en production avec les vraies API.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from agents.core.budget import Budget
from agents.core.bus import EventBus, NullSink
from agents.core.errors import AgentError, BudgetExceeded
from agents.core.llm import LLMProvider
from agents.core.models import Message, Usage

MAX_QUESTION_CHARS = 2000
MAX_CONTRIBUTION_CHARS = 1200
ANONYM_LABELS = "ABCDEFGH"

DEFAULT_MEMBER_PROMPT = """Tu es membre d'un conseil de plusieurs IA.

Tu reponds seul a la question, sans voir les autres membres. Sois precis et
concis : 6 lignes maximum, en francais.

Regles :
- commence par la reponse directe, puis 2 a 3 points d'appui ;
- si un chiffre ou un fait n'est pas verifiable, dis-le explicitement ;
- n'invente aucune source, aucun chiffre, aucune citation ;
- pas de formule d'introduction du type "en tant qu'IA"."""

DEFAULT_REBUTTAL_PROMPT = """Tu es membre d'un conseil de plusieurs IA. Deuxieme tour.

Tu recois ta propre reponse et les reponses **anonymisees** des autres membres.

Regles :
- signale les erreurs factuelles que tu repere chez les autres (cite A, B, C) ;
- corrige ta propre reponse si un autre membre a raison ;
- si tu maintiens ta position, explique pourquoi en une phrase ;
- termine par "Reponse revisee:" suivie de ta version finale, en 4 lignes maximum."""

DEFAULT_JUDGE_PROMPT = """Tu es le JUGE d'un conseil de plusieurs IA.

Tu recois la question et les reponses finales de chaque membre, avec leur nom.

Produis la reponse finale, en francais, structuree exactement ainsi :

## Consensus
Les points sur lesquels les membres s'accordent (2 a 4 puces).

## Divergences
Les points de desaccord, en nommant les membres concernes. Si aucun desaccord,
ecris "Aucune divergence majeure".

## Reponse finale
La reponse a la question, en t'appuyant uniquement sur ce que les membres ont
affirme. N'ajoute aucun fait nouveau. Si les membres sont incertains, dis-le.

## Confiance
Un niveau : eleve, moyen ou faible, avec une justification en une phrase."""


@dataclass(frozen=True, slots=True)
class Member:
    """Un siege du conseil : une etiquette lisible et un provider."""

    label: str
    provider: LLMProvider
    persona: str = ""

    @property
    def name(self) -> str:
        return self.label


@dataclass(frozen=True, slots=True)
class CouncilConfig:
    """Reglages de deliberation."""

    rounds: int = 2
    concurrency: int = 3
    member_timeout_s: float = 60.0
    total_timeout_s: float = 240.0
    max_tokens: int = 700
    temperature: float = 0.2

    def __post_init__(self) -> None:
        if self.rounds < 1:
            raise ValueError("rounds doit etre >= 1")
        if self.concurrency < 1:
            raise ValueError("concurrency doit etre >= 1")
        if self.member_timeout_s <= 0 or self.total_timeout_s <= 0:
            raise ValueError("les timeouts doivent etre > 0")


@dataclass(slots=True)
class Contribution:
    """Une prise de parole (tour 1 = proposition, tour 2 = revision)."""

    label: str
    round: int
    text: str = ""
    ok: bool = True
    error: str | None = None
    usage: Usage = field(default_factory=Usage)
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "round": self.round,
            "ok": self.ok,
            "text": self.text,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 1),
            "usage": self.usage.to_dict(),
        }


@dataclass(slots=True)
class CouncilReport:
    """Compte rendu d'une deliberation."""

    question: str
    members: tuple[str, ...]
    contributions: list[Contribution]
    answer: str
    judge: str
    usage: Usage
    duration_ms: float
    status: Literal["succeeded", "partial", "failed"]
    errors: list[str] = field(default_factory=list)

    def final_by_member(self) -> dict[str, Contribution]:
        """Derniere contribution valide de chaque membre."""
        latest: dict[str, Contribution] = {}
        for contribution in sorted(self.contributions, key=lambda item: item.round):
            if contribution.ok:
                latest[contribution.label] = contribution
        return latest

    def to_dict(self) -> dict[str, object]:
        return {
            "question": self.question,
            "members": list(self.members),
            "judge": self.judge,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 1),
            "usage": self.usage.to_dict(),
            "errors": list(self.errors),
            "contributions": [item.to_dict() for item in self.contributions],
            "answer": self.answer,
        }


class Council:
    """Fait deliberer plusieurs modeles puis fusionne leurs reponses."""

    def __init__(
        self,
        members: Sequence[Member],
        *,
        judge: Member | None = None,
        config: CouncilConfig | None = None,
        budget: Budget | None = None,
        bus: EventBus | None = None,
    ) -> None:
        if not members:
            raise AgentError("un conseil requiert au moins un membre")
        labels = [member.label for member in members]
        if len(set(labels)) != len(labels):
            raise AgentError(
                f"etiquettes de membres dupliquees: {labels}",
                hint="donner un nom distinct a chaque siege du conseil",
            )
        self.members = tuple(members)
        self.judge = judge or members[0]
        self.config = config or CouncilConfig()
        self.budget = budget or Budget()
        self.bus = bus or EventBus([NullSink()])

    # ------------------------------------------------------------------ API
    async def deliberate(self, question: str) -> CouncilReport:
        """Execute la deliberation complete et retourne un rapport."""
        cleaned = " ".join(question.split())
        if not cleaned:
            raise AgentError("question vide", hint="passer une question en argument")
        if len(cleaned) > MAX_QUESTION_CHARS:
            raise AgentError(
                f"question trop longue (> {MAX_QUESTION_CHARS} caracteres)",
                hint="resumer la question",
            )

        started = time.perf_counter()
        self.bus.emit(
            "council.start",
            question=cleaned[:200],
            members=[member.label for member in self.members],
            rounds=self.config.rounds,
        )
        contributions: list[Contribution] = []
        errors: list[str] = []

        try:
            proposals = await asyncio.wait_for(
                self._round_one(cleaned), timeout=self.config.total_timeout_s
            )
        except (TimeoutError, BudgetExceeded) as exc:
            proposals = []
            errors.append(self._describe_stop(exc))
        contributions.extend(proposals)

        if self.config.rounds >= 2:
            revisable = [item for item in proposals if item.ok]
            if revisable:
                try:
                    contributions.extend(
                        await asyncio.wait_for(
                            self._round_two(cleaned, revisable),
                            timeout=self.config.total_timeout_s,
                        )
                    )
                except (TimeoutError, BudgetExceeded) as exc:
                    errors.append(self._describe_stop(exc))

        finals = self._final_by_member(contributions)
        for contribution in contributions:
            if not contribution.ok and contribution.error:
                errors.append(f"{contribution.label}: {contribution.error}")

        if not finals:
            answer = (
                "Aucun membre du conseil n'a produit de reponse exploitable. "
                f"Erreurs: {'; '.join(errors) or 'inconnues'}."
            )
            report = self._report(
                cleaned, contributions, answer, "aucun", errors, started, status="failed"
            )
            self.bus.emit("council.end", status="failed", members=0)
            return report

        answer, judge_usage = await self._judge_answer(cleaned, finals, errors)
        status: Literal["succeeded", "partial", "failed"] = (
            "succeeded" if len(finals) == len(self.members) and not errors else "partial"
        )
        report = self._report(
            cleaned,
            contributions,
            answer,
            self.judge.label,
            errors,
            started,
            status=status,
            extra_usage=judge_usage,
        )
        self.bus.emit(
            "council.end",
            status=status,
            members=len(finals),
            tokens=report.usage.total_tokens,
        )
        return report

    def deliberate_sync(self, question: str) -> CouncilReport:
        """Variante synchrone (CLI, notebooks)."""
        return asyncio.run(self.deliberate(question))

    # ---------------------------------------------------------------- tours
    async def _round_one(self, question: str) -> list[Contribution]:
        semaphore = asyncio.Semaphore(self.config.concurrency)

        async def ask(member: Member) -> Contribution:
            async with semaphore:
                return await self._ask(
                    member,
                    round_number=1,
                    user_content=f"[[QUESTION]]\n{question}",
                    system=self._member_system(member),
                )

        self.bus.emit("council.round", round=1, members=len(self.members))
        return list(await asyncio.gather(*(ask(member) for member in self.members)))

    async def _round_two(
        self, question: str, proposals: Sequence[Contribution]
    ) -> list[Contribution]:
        by_label = {item.label: item for item in proposals}
        semaphore = asyncio.Semaphore(self.config.concurrency)

        async def ask(member: Member) -> Contribution:
            own = by_label.get(member.label)
            if own is None:
                return Contribution(
                    label=member.label, round=2, ok=False, error="aucune proposition au tour 1"
                )
            others = self._anonymised_others(member.label, proposals)
            async with semaphore:
                return await self._ask(
                    member,
                    round_number=2,
                    user_content=(
                        f"[[QUESTION]]\n{question}\n\n"
                        f"[[VOTRE REPONSE]]\n{own.text[:MAX_CONTRIBUTION_CHARS]}\n\n"
                        f"[[REPONSES ANONYMES]]\n{others}"
                    ),
                    system=f"{self._member_system(member)}\n\n{DEFAULT_REBUTTAL_PROMPT}",
                )

        self.bus.emit("council.round", round=2, members=len(proposals))
        return list(await asyncio.gather(*(ask(member) for member in self.members)))

    async def _ask(
        self, member: Member, *, round_number: int, user_content: str, system: str
    ) -> Contribution:
        started = time.perf_counter()
        messages = [
            Message(role="system", content=system),
            Message(role="user", content=user_content),
        ]
        self.bus.emit("council.member.start", member=member.label, round=round_number)
        try:
            self.budget.check_deadline()
            response = await asyncio.wait_for(
                member.provider.complete(
                    messages,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    metadata={
                        "agent_role": "council_member",
                        "member": member.label,
                        "round": round_number,
                    },
                ),
                timeout=self.config.member_timeout_s,
            )
            await self.budget.consume(response.usage)
        except BudgetExceeded:
            raise
        except TimeoutError:
            return Contribution(
                label=member.label,
                round=round_number,
                ok=False,
                error=f"timeout du membre ({self.config.member_timeout_s:.0f}s)",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        except Exception as exc:
            return Contribution(
                label=member.label,
                round=round_number,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=(time.perf_counter() - started) * 1000,
            )

        text = response.text.strip()
        duration_ms = (time.perf_counter() - started) * 1000
        self.bus.emit(
            "council.member.end",
            member=member.label,
            round=round_number,
            chars=len(text),
            ok=bool(text),
        )
        if not text:
            return Contribution(
                label=member.label,
                round=round_number,
                ok=False,
                error="reponse vide",
                usage=response.usage,
                duration_ms=duration_ms,
            )
        return Contribution(
            label=member.label,
            round=round_number,
            text=text,
            usage=response.usage,
            duration_ms=duration_ms,
        )

    # ---------------------------------------------------------------- juge
    async def _judge_answer(
        self, question: str, finals: dict[str, Contribution], errors: Sequence[str]
    ) -> tuple[str, Usage]:
        blocks = [
            f"### {label}\n{contribution.text[:MAX_CONTRIBUTION_CHARS]}"
            for label, contribution in finals.items()
        ]
        content = f"[[QUESTION]]\n{question}\n\n[[CONTRIBUTIONS]]\n" + "\n\n".join(blocks)
        if errors:
            content += "\n\n[[ECHECS]]\n" + "\n".join(f"- {error}" for error in errors)

        messages = [
            Message(role="system", content=DEFAULT_JUDGE_PROMPT),
            Message(role="user", content=content),
        ]
        self.bus.emit("council.judge.start", judge=self.judge.label)
        usage = Usage()
        try:
            response = await asyncio.wait_for(
                self.judge.provider.complete(
                    messages,
                    temperature=0.0,
                    max_tokens=max(self.config.max_tokens, 900),
                    metadata={"agent_role": "council_judge", "member": self.judge.label},
                ),
                timeout=self.config.member_timeout_s * 2,
            )
            await self.budget.consume(response.usage)
            usage = response.usage
            answer = response.text.strip()
        except Exception as exc:
            self.bus.emit("council.judge.error", error=f"{type(exc).__name__}"[:120])
            answer = ""

        if answer:
            return answer, usage
        return self._fallback_answer(question, finals), usage

    @staticmethod
    def _fallback_answer(question: str, finals: dict[str, Contribution]) -> str:
        """Synthese assemblee sans juge : jamais vide, jamais trompeuse."""
        lines = [
            "## Reponse finale",
            "",
            f"Question : {question}",
            "",
            "_Le juge n'a pas pu produire de synthese : voici les contributions brutes._",
            "",
        ]
        for label, contribution in finals.items():
            lines.append(f"**{label}**")
            lines.append("")
            lines.append(" ".join(contribution.text.split())[:600])
            lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------- helpers
    def _report(
        self,
        question: str,
        contributions: list[Contribution],
        answer: str,
        judge: str,
        errors: list[str],
        started: float,
        *,
        status: Literal["succeeded", "partial", "failed"],
        extra_usage: Usage | None = None,
    ) -> CouncilReport:
        usage = Usage.merge([item.usage for item in contributions]) + (extra_usage or Usage())
        return CouncilReport(
            question=question,
            members=tuple(member.label for member in self.members),
            contributions=contributions,
            answer=answer,
            judge=judge,
            usage=usage,
            duration_ms=(time.perf_counter() - started) * 1000,
            status=status,
            errors=discard_duplicates(errors),
        )

    @staticmethod
    def _member_system(member: Member) -> str:
        if member.persona:
            return f"{DEFAULT_MEMBER_PROMPT}\n\nAngle a privilegier : {member.persona}"
        return DEFAULT_MEMBER_PROMPT

    @staticmethod
    def _anonymised_others(own_label: str, proposals: Sequence[Contribution]) -> str:
        """Presente les autres reponses sous les etiquettes A, B, C...

        Le nom de l'auteur est aussi remplace *dans le texte* : une reponse qui
        signe "Claude" ou "ChatGPT" rendrait l'anonymisation inoperante et
        re-introduirait le biais de marque que ce tour cherche a neutraliser.
        """
        healthy = [item for item in proposals if item.ok]
        index = [item.label for item in healthy].index(own_label)
        others = [item for item in healthy if item.label != own_label]
        ordered = others[index:] + others[:index]  # ordre decale : stable et neutre
        blocks: list[str] = []
        for position, item in enumerate(ordered):
            alias = ANONYM_LABELS[position]
            text = item.text
            if item.label:
                text = re.sub(re.escape(item.label), alias, text, flags=re.IGNORECASE)
            blocks.append(f"### {alias}\n{text[:MAX_CONTRIBUTION_CHARS]}")
        return "\n\n".join(blocks) or "Aucune autre reponse exploitable."

    @staticmethod
    def _final_by_member(contributions: Sequence[Contribution]) -> dict[str, Contribution]:
        latest: dict[str, Contribution] = {}
        for contribution in sorted(contributions, key=lambda item: item.round):
            if contribution.ok:
                latest[contribution.label] = contribution
        return latest

    @staticmethod
    def _describe_stop(exc: BaseException) -> str:
        if isinstance(exc, BudgetExceeded):
            return f"budget epuise: {exc}"
        return "deliberation interrompue par le timeout global"


def discard_duplicates(items: Sequence[str]) -> list[str]:
    """Conserve l'ordre en supprimant les erreurs repetees."""
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique
