"""Budget d'execution : plafonds de tokens, d'appels LLM et de temps.

Un run multi-agents peut s'emballer (boucles ReAct, retries, parallelisme). Le
budget est donc un garde-fou *obligatoire* : il est consomme a chaque appel LLM
et leve :class:`BudgetExceeded` avant que la facture ne derive.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from agents.core.errors import BudgetExceeded
from agents.core.models import Usage


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    """Etat du budget a un instant donne (pour les traces et le rapport)."""

    llm_calls: int
    total_tokens: int
    elapsed_s: float
    max_llm_calls: int
    max_tokens: int
    max_seconds: float

    @property
    def calls_left(self) -> int:
        return max(0, self.max_llm_calls - self.llm_calls)

    @property
    def tokens_left(self) -> int:
        return max(0, self.max_tokens - self.total_tokens)

    def to_dict(self) -> dict[str, Any]:
        return {
            "llm_calls": self.llm_calls,
            "total_tokens": self.total_tokens,
            "elapsed_s": round(self.elapsed_s, 2),
            "calls_left": self.calls_left,
            "tokens_left": self.tokens_left,
        }


@dataclass
class Budget:
    """Compteur de consommation sur, partage par tous les agents d'un run.

    L'acces est serialise par un verrou asyncio : plusieurs workers concurrents
    peuvent consommer le budget sans depasser les plafonds.
    """

    max_llm_calls: int = 60
    max_tokens: int = 200_000
    max_seconds: float = 180.0
    _usage: Usage = field(default_factory=Usage, init=False)
    _started_at: float = field(default=0.0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self) -> None:
        if self.max_llm_calls < 1:
            raise ValueError("max_llm_calls doit etre >= 1")
        if self.max_tokens < 1:
            raise ValueError("max_tokens doit etre >= 1")
        if self.max_seconds <= 0:
            raise ValueError("max_seconds doit etre > 0")
        self._started_at = time.monotonic()

    @property
    def usage(self) -> Usage:
        return self._usage

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self._started_at

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.max_seconds - self.elapsed_s)

    def snapshot(self) -> BudgetSnapshot:
        return BudgetSnapshot(
            llm_calls=self._usage.llm_calls,
            total_tokens=self._usage.total_tokens,
            elapsed_s=self.elapsed_s,
            max_llm_calls=self.max_llm_calls,
            max_tokens=self.max_tokens,
            max_seconds=self.max_seconds,
        )

    def check_deadline(self) -> None:
        """Leve :class:`BudgetExceeded` si la duree maximale est atteinte."""
        if self.elapsed_s >= self.max_seconds:
            raise BudgetExceeded(
                f"duree maximale depassee ({self.max_seconds:.0f}s)",
                hint="augmenter --max-seconds ou reduire le nombre de taches",
            )

    async def consume(self, usage: Usage) -> None:
        """Reserve un appel LLM et ses tokens, ou leve :class:`BudgetExceeded`."""
        async with self._lock:
            self.check_deadline()
            if self._usage.llm_calls + max(1, usage.llm_calls) > self.max_llm_calls:
                raise BudgetExceeded(
                    f"quota d'appels LLM epuise ({self.max_llm_calls})",
                    hint="augmenter --max-llm-calls ou reduire le nombre de taches",
                )
            projected = self._usage.total_tokens + usage.total_tokens
            if projected > self.max_tokens:
                raise BudgetExceeded(
                    f"quota de tokens epuise ({self.max_tokens} max, {projected} demandes)",
                    hint="augmenter --max-tokens ou raccourcir les instructions",
                )
            self._usage = self._usage + Usage(
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                llm_calls=max(1, usage.llm_calls),
            )

    def reset(self) -> None:
        """Remet le compteur a zero (utile pour reutiliser un budget en test)."""
        self._usage = Usage()
        self._started_at = time.monotonic()
