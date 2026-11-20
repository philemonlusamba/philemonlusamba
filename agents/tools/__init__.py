"""Outils exposes aux agents, avec leur schema et leurs garde-fous.

Un outil n'est jamais "monte" en dur dans un agent : il est enregistre dans un
:class:`ToolRegistry`, ce qui rend l'ensemble testable et remplacable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.core.errors import PolicyError
from agents.core.registry import ToolRegistry
from agents.tools import calc as calc_tools
from agents.tools import text as text_tools
from agents.tools.files import FileSandbox
from agents.tools.search import Corpus

__all__ = ["FileSandbox", "build_registry"]

_DEFAULT_WORKSPACE = Path.cwd()
_DEFAULT_CORPUS = Path(__file__).resolve().parents[1] / "data" / "corpus"


def build_registry(
    *,
    workspace: str | Path | None = None,
    corpus_dir: str | Path | None = None,
    allow_write: bool = False,
) -> ToolRegistry:
    """Construit le registre complet (calcul, recherche, fichiers, texte).

    Les outils sont regroupes ici pour que les tests puissent construire un
    registre isole sur ``tmp_path`` sans toucher au disque du projet.
    """
    registry = ToolRegistry()

    registry.register(
        name="calc_evaluate",
        description=(
            "Evalue une expression arithmetique (+, -, *, /, //, %, ** et fonctions "
            "sqrt, log, sin, round, min, max...). Retourne la valeur exacte."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "expression": {"type": "string", "minLength": 1, "maxLength": 300},
            },
            "required": ["expression"],
            "additionalProperties": False,
        },
        handler=calc_tools.evaluate,
    )

    registry.register(
        name="text_stats",
        description="Compte caracteres, mots, phrases et paragraphes d'un texte.",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string", "minLength": 1, "maxLength": 20000}},
            "required": ["text"],
            "additionalProperties": False,
        },
        handler=_text_stats,
    )

    registry.register(
        name="text_summarize",
        description="Resume extractif d'un texte (selection des phrases les plus informatives).",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "minLength": 1, "maxLength": 20000},
                "max_sentences": {"type": "integer", "minimum": 1, "maximum": 8},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
        handler=_summarize,
    )

    corpus = _load_corpus(corpus_dir)
    registry.register(
        name="doc_search",
        description=(
            "Recherche par pertinence (BM25) dans le corpus documentaire local et retourne "
            "des extraits sources avec leur fichier."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 2, "maxLength": 300},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=lambda query, top_k=3: _search(corpus, query, top_k),
    )

    sandbox = FileSandbox(
        root=Path(workspace) if workspace is not None else _DEFAULT_WORKSPACE,
        allow_write=allow_write,
    )
    registry.register(
        name="file_read",
        description="Lit un fichier texte du workspace (chemins relatifs uniquement, sandbox).",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1, "maxLength": 300},
                "max_chars": {"type": "integer", "minimum": 200, "maximum": 20000},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        handler=lambda path, max_chars=4000: sandbox.read(path, max_chars=max_chars),
    )

    registry.register(
        name="file_list",
        description="Liste les fichiers et repertoires du workspace (sandbox).",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "maxLength": 300},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "additionalProperties": False,
        },
        handler=lambda path=".", limit=50: "\n".join(sandbox.list_dir(path, limit=limit)),
    )

    if allow_write:
        registry.register(
            name="file_write",
            description="Ecrit un fichier texte dans le workspace (active explicitement).",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1, "maxLength": 300},
                    "content": {"type": "string", "maxLength": 20000},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            handler=lambda path, content: sandbox.write(path, content),
        )

    return registry


def _load_corpus(corpus_dir: str | Path | None) -> Corpus:
    directory = Path(corpus_dir) if corpus_dir is not None else _DEFAULT_CORPUS
    try:
        return Corpus.from_directory(directory)
    except Exception:
        return Corpus(documents=[])


def _search(corpus: Corpus, query: str, top_k: int) -> str:
    if not corpus.documents:
        raise PolicyError(
            "aucun corpus documentaire charge",
            hint="lancer avec --corpus chemin/vers/documents",
        )
    hits = corpus.search(query, top_k=top_k)
    if not hits:
        return f"Aucun document ne correspond a : {query}"
    lines = []
    for rank, hit in enumerate(hits, start=1):
        lines.append(f"{rank}. [{hit.path}] {hit.title} (score {hit.score:.2f})\n   {hit.snippet}")
    return "\n".join(lines)


def _text_stats(text: str) -> str:
    return text_tools.stats(text)


def _summarize(text: str, max_sentences: int = 3) -> str:
    return text_tools.summarize(text, max_sentences=max_sentences)


def describe(registry: ToolRegistry) -> list[dict[str, Any]]:
    """Resume serialisable des outils (utilise par ``agents tools``)."""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "required": spec.input_schema.get("required", []),
            "timeout_s": spec.timeout_s,
        }
        for spec in registry.specs()
    ]
