"""Tests des outils documentaires et textuels, via le registre (jamais en direct)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from agents.core.errors import PolicyError, ToolError
from agents.tools import build_registry
from agents.tools.search import Corpus, tokenize
from agents.tools.text import stats, summarize


def invoke(registry, name: str, **arguments) -> str:
    return asyncio.run(registry.invoke(name, arguments))


# ------------------------------------------------------------------ corpus
def test_bm25_ranks_relevant_document_first(registry) -> None:
    output = invoke(registry, "doc_search", query="sandbox chemins fichiers", top_k=2)
    assert output.splitlines()[0].find("securite.md") != -1


def test_search_is_case_and_accent_insensitive(corpus_dir: Path) -> None:
    corpus = Corpus.from_directory(corpus_dir)
    hits = corpus.search("SÉCURITÉ")
    assert hits and hits[0].path == "securite.md"


def test_search_returns_snippet_with_term(corpus_dir: Path) -> None:
    hits = Corpus.from_directory(corpus_dir).search("parallele", top_k=1)
    assert hits[0].snippet
    assert hits[0].score > 0


def test_search_without_match_returns_empty(corpus_dir: Path) -> None:
    assert Corpus.from_directory(corpus_dir).search("zoroastre") == []


def test_search_empty_query_is_refused(corpus_dir: Path) -> None:
    with pytest.raises(ToolError, match="requete vide"):
        Corpus.from_directory(corpus_dir).search("le la les")


def test_corpus_missing_directory() -> None:
    with pytest.raises(ToolError, match="introuvable"):
        Corpus.from_directory("/chemin/qui/n/existe/pas")


def test_corpus_empty_directory(tmp_path: Path) -> None:
    with pytest.raises(ToolError, match="aucun document"):
        Corpus.from_directory(tmp_path)


def test_no_corpus_loaded_gives_policy_error(tmp_path: Path) -> None:
    registry = build_registry(workspace=tmp_path, corpus_dir=tmp_path)
    with pytest.raises(PolicyError, match="aucun corpus"):
        invoke(registry, "doc_search", query="quoi")


def test_tokenize_removes_stopwords() -> None:
    assert tokenize("Le planner et les workers") == ["planner", "workers"]


# -------------------------------------------------------------------- texte
def test_text_stats(registry) -> None:
    output = invoke(registry, "text_stats", text="Bonjour le monde. Deuxieme phrase ici.")
    assert "mots=" in output and "phrases=" in output


def test_text_summarize_keeps_key_sentence(registry) -> None:
    text = (
        "Le chat dort sur le canape. "
        "La facturation indique un prix unitaire de 249,99 USD pour un siege ergonomique. "
        "Il pleut dehors depuis ce matin. "
        "Le prix unitaire du siege ergonomique reste le point central du dossier."
    )
    output = invoke(registry, "text_summarize", text=text, max_sentences=1)
    assert "prix unitaire" in output


def test_text_stats_rejects_empty() -> None:
    with pytest.raises(ToolError):
        stats("   ")
    with pytest.raises(ToolError):
        summarize("")


def test_summarize_handles_short_text() -> None:
    assert "court" in summarize("tres court")


# ------------------------------------------------------------------ fichiers
def test_file_read_and_list_through_registry(registry) -> None:
    assert "budget" in invoke(registry, "file_read", path="notes.txt")
    listing = invoke(registry, "file_list")
    assert "notes.txt" in listing


def test_file_read_escape_is_refused(registry) -> None:
    with pytest.raises(PolicyError):
        invoke(registry, "file_read", path="../../etc/passwd")


def test_file_write_requires_explicit_activation(registry) -> None:
    assert "file_write" not in registry
    with pytest.raises(ToolError, match="outil inconnu"):
        invoke(registry, "file_write", path="x.txt", content="y")


def test_file_write_available_when_enabled(workspace: Path, corpus_dir: Path) -> None:
    registry = build_registry(workspace=workspace, corpus_dir=corpus_dir, allow_write=True)
    assert "file_write" in registry
    assert "ecrits" in invoke(registry, "file_write", path="sortie.txt", content="ok")


# -------------------------------------------------------------------- calcul
def test_calc_tool_through_registry(registry) -> None:
    assert "2999.88" in invoke(registry, "calc_evaluate", expression="12*249.99")


def test_calc_tool_rejects_code(registry) -> None:
    with pytest.raises(PolicyError):
        invoke(registry, "calc_evaluate", expression="__import__('os')")
