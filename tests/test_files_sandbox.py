"""Tests du sandbox fichiers : le confinement est le comportement a prouver."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from agents.core.errors import PolicyError, ToolError
from agents.tools.files import FileSandbox


@pytest.fixture
def sandbox(workspace: Path) -> FileSandbox:
    return FileSandbox(root=workspace)


def test_read_inside_root(sandbox: FileSandbox) -> None:
    assert "budget" in sandbox.read("notes.txt")


def test_read_nested_file(sandbox: FileSandbox) -> None:
    assert "Detail" in sandbox.read("sous_dossier/detail.md")


@pytest.mark.parametrize(
    "path",
    [
        "../secrets.txt",
        "sous_dossier/../../secrets.txt",
        "/etc/passwd",
        "~/notes.txt",
        "notes.txt\x00",
        "",
    ],
)
def test_paths_outside_sandbox_are_refused(sandbox: FileSandbox, path: str) -> None:
    with pytest.raises(PolicyError):
        sandbox.resolve(path)


def test_symlink_escape_is_refused(sandbox: FileSandbox, tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("confidentiel", encoding="utf-8")
    link = sandbox.root / "lien.txt"
    try:
        os.symlink(secret, link)
    except (OSError, NotImplementedError):  # pragma: no cover - plateforme sans symlink
        pytest.skip("liens symboliques indisponibles")
    with pytest.raises(PolicyError, match="hors du sandbox"):
        sandbox.resolve("lien.txt")


def test_missing_file_is_a_tool_error(sandbox: FileSandbox) -> None:
    with pytest.raises(ToolError, match="introuvable"):
        sandbox.read("absent.txt")


def test_read_truncates(sandbox: FileSandbox) -> None:
    big = sandbox.root / "gros.txt"
    big.write_text("a" * 5000, encoding="utf-8")
    output = sandbox.read("gros.txt", max_chars=100)
    assert "tronquee" in output
    assert len(output) < 300


def test_oversized_file_refused(workspace: Path) -> None:
    sandbox = FileSandbox(root=workspace, max_bytes=10)
    (workspace / "gros.txt").write_text("a" * 100, encoding="utf-8")
    with pytest.raises(PolicyError, match="volumineux"):
        sandbox.read("gros.txt")


def test_write_disabled_by_default(sandbox: FileSandbox) -> None:
    with pytest.raises(PolicyError, match="ecriture desactivee"):
        sandbox.write("nouveau.txt", "contenu")


def test_write_allowed_when_explicit(workspace: Path) -> None:
    sandbox = FileSandbox(root=workspace, allow_write=True)
    message = sandbox.write("sortie/resultat.txt", "ok")
    assert "ecrits" in message
    assert (workspace / "sortie" / "resultat.txt").read_text(encoding="utf-8") == "ok"


def test_write_outside_root_refused(workspace: Path) -> None:
    sandbox = FileSandbox(root=workspace, allow_write=True)
    with pytest.raises(PolicyError):
        sandbox.write("../evasion.txt", "x")


def test_list_dir_sorted_and_marked(sandbox: FileSandbox) -> None:
    entries = sandbox.list_dir(".")
    assert "notes.txt" in entries
    assert "sous_dossier/" in entries


def test_list_dir_on_file_fails(sandbox: FileSandbox) -> None:
    with pytest.raises(ToolError, match="pas un repertoire"):
        sandbox.list_dir("notes.txt")


def test_root_is_created_if_missing(tmp_path: Path) -> None:
    FileSandbox(root=tmp_path / "nouveau" / "dossier")
    assert (tmp_path / "nouveau" / "dossier").is_dir()
