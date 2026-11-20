"""Bus d'evenements : trace lisible en console, en JSONL, ou collecte en memoire.

Un orchestrateur concurrent est difficile a deboguer sans trace ordonnee. Chaque
etape (plan, tache, outil, appel LLM) emet un evenement horodate et tronque, ce
qui donne une chronologie exploitable sans relire le code.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

MAX_FIELD_CHARS = 600

_LEVEL_COLORS = {
    "run.start": "\033[36m",  # cyan
    "task.start": "\033[34m",  # bleu
    "task.end": "\033[32m",  # vert
    "task.retry": "\033[33m",  # jaune
    "error": "\033[31m",  # rouge
}
_RESET = "\033[0m"


def _truncate(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_FIELD_CHARS:
        return value[:MAX_FIELD_CHARS] + f"...[{len(value) - MAX_FIELD_CHARS} chars tronques]"
    return value


class Sink(Protocol):
    """Destination d'evenements."""

    def emit(self, event: dict[str, Any]) -> None: ...


class EventBus:
    """Distribue un evenement a tous les sinks, sans jamais faire echouer le run."""

    def __init__(self, sinks: Sequence[Sink] | None = None, *, run_id: str = "-") -> None:
        self._sinks: list[Sink] = list(sinks or [])
        self._run_id = run_id
        self._t0 = time.monotonic()

    @property
    def run_id(self) -> str:
        return self._run_id

    def add_sink(self, sink: Sink) -> None:
        self._sinks.append(sink)

    def emit(self, kind: str, **fields: Any) -> None:
        event = {
            "ts": round(time.monotonic() - self._t0, 4),
            "run_id": self._run_id,
            "event": kind,
            **{key: _truncate(value) for key, value in fields.items()},
        }
        for sink in self._sinks:
            try:
                sink.emit(event)
            except Exception:
                continue


class NullSink:
    """Sink inerte (par defaut en bibliotheque)."""

    def emit(self, event: dict[str, Any]) -> None:
        return None


class CollectorSink:
    """Conserve les evenements en memoire : pratique pour les tests et assertions."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def kinds(self) -> list[str]:
        return [event["event"] for event in self.events]

    def of_kind(self, kind: str) -> list[dict[str, Any]]:
        return [event for event in self.events if event["event"] == kind]


class JsonlSink:
    """Ecrit un fichier JSONL (une ligne par evenement), robuste aux gros volumes."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def emit(self, event: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")


class ConsoleSink:
    """Affichage compact et colore, desactive automatiquement si stdout n'est pas un TTY."""

    def __init__(self, stream: Any | None = None, *, color: bool | None = None) -> None:
        self.stream = stream or sys.stderr
        is_tty = bool(getattr(self.stream, "isatty", lambda: False)())
        self.color = is_tty if color is None else color

    def emit(self, event: dict[str, Any]) -> None:
        kind = event.get("event", "?")
        if kind in {"llm.request", "llm.response", "tool.result"}:
            return  # trop verbeux en mode normal
        detail = " ".join(
            f"{key}={value}"
            for key, value in event.items()
            if key not in {"ts", "run_id", "event"} and value not in (None, "")
        )
        prefix = _LEVEL_COLORS.get(kind, "") if self.color else ""
        suffix = _RESET if self.color and prefix else ""
        stamp = f"{prefix}[{event.get('ts', 0):>7.2f}s] {kind:<16}{suffix} {detail}"
        print(stamp, file=self.stream)
