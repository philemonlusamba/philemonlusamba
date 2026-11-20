"""Acces fichiers sandboxe.

Un agent qui lit `../../../etc/passwd` ou qui ecrit hors du repertoire de travail
est la faille la plus banale d'un systeme d'agents. Toute resolution de chemin
passe donc ici, avec verification d'appartenance **apres** ``resolve()`` (donc
apres le suivi des liens symboliques), plafond de taille et ecriture desactivee
par defaut.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agents.core.errors import PolicyError, ToolError

DEFAULT_MAX_BYTES = 64_000
DEFAULT_MAX_ENTRIES = 200


@dataclass
class FileSandbox:
    """Vue restreinte d'un repertoire racine."""

    root: Path
    allow_write: bool = False
    max_bytes: int = DEFAULT_MAX_BYTES
    max_entries: int = DEFAULT_MAX_ENTRIES

    def __post_init__(self) -> None:
        self.root = Path(self.root).expanduser().resolve()
        if not self.root.exists():
            self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise ValueError(f"la racine du sandbox n'est pas un repertoire: {self.root}")

    def resolve(self, relative: str) -> Path:
        """Resout un chemin relatif en garantissant qu'il reste dans la racine."""
        if not isinstance(relative, str) or not relative.strip():
            raise PolicyError("chemin vide", hint='utiliser "." pour la racine')
        if "\x00" in relative:
            raise PolicyError("caractere NUL dans le chemin")
        candidate = Path(relative)
        if candidate.is_absolute() or relative.startswith("~"):
            raise PolicyError(
                f"chemin absolu refuse: {relative}",
                hint="les chemins doivent etre relatifs a la racine du workspace",
            )
        resolved = (self.root / candidate).resolve(strict=False)
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise PolicyError(
                f"chemin hors du sandbox refuse: {relative}",
                hint=f"seuls les chemins sous {self.root} sont accessibles",
            ) from exc
        return resolved

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def read(self, relative: str, *, max_chars: int = 4000) -> str:
        path = self.resolve(relative)
        if not path.exists():
            raise ToolError(
                f"fichier introuvable: {relative}",
                hint="utiliser file_list pour voir les fichiers disponibles",
            )
        if not path.is_file():
            raise ToolError(f"ce n'est pas un fichier: {relative}")
        size = path.stat().st_size
        if size > self.max_bytes:
            raise PolicyError(
                f"fichier trop volumineux ({size} octets > {self.max_bytes})",
                hint="augmenter max_bytes a la construction du sandbox",
            )
        text = path.read_bytes().decode("utf-8", errors="replace")
        if len(text) > max_chars:
            return f"{text[:max_chars]}\n...[lecture tronquee a {max_chars} caracteres]"
        return text

    def list_dir(self, relative: str = ".", *, limit: int = 50) -> list[str]:
        path = self.resolve(relative)
        if not path.exists():
            raise ToolError(f"repertoire introuvable: {relative}")
        if not path.is_dir():
            raise ToolError(f"ce n'est pas un repertoire: {relative}")
        entries: list[str] = []
        for entry in sorted(path.iterdir(), key=lambda item: (item.is_file(), item.name)):
            if len(entries) >= min(limit, self.max_entries):
                entries.append("...[liste tronquee]")
                break
            suffix = "/" if entry.is_dir() else ""
            entries.append(f"{self.relative(entry)}{suffix}")
        return entries

    def write(self, relative: str, content: str) -> str:
        if not self.allow_write:
            raise PolicyError(
                "ecriture desactivee dans ce sandbox",
                hint="FileSandbox(allow_write=True) est requis explicitement",
            )
        if len(content.encode("utf-8")) > self.max_bytes:
            raise PolicyError(f"contenu trop volumineux (> {self.max_bytes} octets)")
        path = self.resolve(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"{len(content)} caracteres ecrits dans {self.relative(path)}"
