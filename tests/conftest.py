"""Fixtures partagees : corpus temporaire, registre isole, bus de collecte."""

from __future__ import annotations

from pathlib import Path

import pytest
from agents.core.bus import CollectorSink, EventBus
from agents.core.providers.mock import MockProvider
from agents.core.registry import ToolRegistry
from agents.tools import build_registry

CORPUS = {
    "architecture.md": (
        "# Architecture\n\n"
        "Le planner decompose l'objectif en un graphe acyclique de taches. Les workers "
        "executent les taches en parallele, puis le critique evalue chaque resultat.\n"
    ),
    "securite.md": (
        "# Securite\n\n"
        "Le calcul arithmetique n'utilise jamais eval. Les chemins de fichiers sont "
        "sandboxes et les arguments d'outils valides contre un schema.\n"
    ),
    "facturation.md": (
        "# Facturation\n\n"
        "Le prix unitaire d'un siege ergonomique est de 249,99 USD hors taxes. "
        "La livraison est gratuite au-dela de dix unites.\n"
    ),
}


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "workspace"
    path.mkdir()
    (path / "notes.txt").write_text("note interne: revoir le budget", encoding="utf-8")
    (path / "sous_dossier").mkdir()
    (path / "sous_dossier" / "detail.md").write_text("# Detail\ntexte", encoding="utf-8")
    return path


@pytest.fixture
def corpus_dir(tmp_path: Path) -> Path:
    path = tmp_path / "corpus"
    path.mkdir()
    for name, content in CORPUS.items():
        (path / name).write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def registry(workspace: Path, corpus_dir: Path) -> ToolRegistry:
    return build_registry(workspace=workspace, corpus_dir=corpus_dir)


@pytest.fixture
def empty_registry() -> ToolRegistry:
    return ToolRegistry()


@pytest.fixture
def mock_provider() -> MockProvider:
    return MockProvider()


@pytest.fixture
def bus() -> tuple[EventBus, CollectorSink]:
    sink = CollectorSink()
    return EventBus([sink], run_id="test-run"), sink
