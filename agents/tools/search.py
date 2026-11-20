"""Recherche documentaire locale (BM25 simplifie, sans dependance).

Sert de "memoire" a l'orchestrateur : les workers citent des passages reels du
corpus plutot que d'inventer des sources. Le scoring est deterministe, donc
testable.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from agents.core.errors import ToolError

_TOKEN_RE = re.compile(r"[a-z0-9àâäéèêëîïôöùûüç']+", re.IGNORECASE)
_STOPWORDS = frozenset(
    {
        "le",
        "la",
        "les",
        "un",
        "une",
        "des",
        "de",
        "du",
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
        "est",
        "sont",
        "par",
        "que",
        "qui",
        "a",
        "d",
        "l",
        "s",
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
        "be",
        "as",
        "on",
        "at",
        "by",
        "it",
        "this",
        "that",
    }
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def fold(text: str) -> str:
    """Minuscule sans accents : "Securité" et "securite" doivent se rencontrer."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char)).lower()


def tokenize(text: str) -> list[str]:
    """Tokenisation simple, insensible a la casse et aux accents, sans mots vides."""
    return [
        token
        for token in (match.group(0) for match in _TOKEN_RE.finditer(fold(text)))
        if token not in _STOPWORDS and len(token) > 1
    ]


@dataclass(frozen=True, slots=True)
class Document:
    path: str
    title: str
    text: str

    @property
    def tokens(self) -> list[str]:
        return tokenize(self.text)


@dataclass(frozen=True, slots=True)
class SearchHit:
    path: str
    title: str
    score: float
    snippet: str

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "title": self.title,
            "score": round(self.score, 3),
            "snippet": self.snippet,
        }


@dataclass
class Corpus:
    """Collection de documents indexes en memoire."""

    documents: list[Document] = field(default_factory=list)
    k1: float = 1.5
    b: float = 0.75

    def __post_init__(self) -> None:
        self._tokens: list[Counter[str]] = []
        self._lengths: list[int] = []
        self._idf: dict[str, float] = {}
        self._avg_length: float = 0.0
        self._reindex()

    def _reindex(self) -> None:
        self._tokens = [Counter(document.tokens) for document in self.documents]
        self._lengths = [sum(counter.values()) for counter in self._tokens]
        total = sum(self._lengths)
        self._avg_length = (total / len(self.documents)) if self.documents else 0.0

        document_frequency: Counter[str] = Counter()
        for counter in self._tokens:
            document_frequency.update(set(counter))
        count = len(self.documents)
        self._idf = {
            term: math.log(1 + (count - freq + 0.5) / (freq + 0.5))
            for term, freq in document_frequency.items()
        }

    def __len__(self) -> int:
        return len(self.documents)

    @classmethod
    def from_directory(
        cls,
        directory: str | Path,
        *,
        patterns: tuple[str, ...] = ("*.md", "*.txt"),
        max_files: int = 200,
        max_chars_per_file: int = 100_000,
    ) -> Corpus:
        """Charge un repertoire de fichiers texte ; echoue clairement s'il est vide."""
        root = Path(directory).expanduser().resolve()
        if not root.is_dir():
            raise ToolError(
                f"corpus introuvable: {root}",
                hint="indiquer un repertoire contenant des .md ou .txt via --corpus",
            )
        paths: list[Path] = []
        for pattern in patterns:
            paths.extend(sorted(root.glob(pattern)))
        paths = [path for path in paths if path.is_file()][:max_files]
        if not paths:
            raise ToolError(
                f"aucun document (.md/.txt) dans {root}",
                hint="ajouter des fichiers dans le corpus ou utiliser un autre repertoire",
            )
        documents = []
        for path in paths:
            text = path.read_text(encoding="utf-8", errors="replace")[:max_chars_per_file]
            title = _first_heading(text) or path.stem.replace("_", " ").replace("-", " ")
            documents.append(Document(path=path.name, title=title, text=text))
        return cls(documents=documents)

    def search(self, query: str, *, top_k: int = 3) -> list[SearchHit]:
        """Retourne les ``top_k`` documents les plus pertinents (score BM25)."""
        terms = tokenize(query)
        if not terms:
            raise ToolError(
                "requete vide apres nettoyage",
                hint="fournir au moins un mot significatif",
            )
        if not self.documents:
            return []

        scores: list[float] = []
        for counter, length in zip(self._tokens, self._lengths, strict=True):
            score = 0.0
            for term in terms:
                frequency = counter.get(term, 0)
                if not frequency:
                    continue
                idf = self._idf.get(term, 0.0)
                denominator = frequency + self.k1 * (
                    1 - self.b + self.b * (length / (self._avg_length or 1.0))
                )
                score += idf * (frequency * (self.k1 + 1)) / denominator
            scores.append(score)

        ranked = sorted(
            zip(self.documents, scores, strict=True),
            key=lambda item: (-item[1], item[0].path),
        )
        hits: list[SearchHit] = []
        for document, score in ranked[: max(1, min(top_k, 10))]:
            if score <= 0:
                continue
            hits.append(
                SearchHit(
                    path=document.path,
                    title=document.title,
                    score=score,
                    snippet=_best_snippet(document.text, terms),
                )
            )
        return hits


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


def _best_snippet(text: str, terms: list[str], *, max_chars: int = 320) -> str:
    """Choisit la phrase contenant le plus de termes de la requete."""
    sentences = [chunk.strip() for chunk in _SENTENCE_SPLIT.split(" ".join(text.split()))]
    best, best_score = "", -1
    for index, sentence in enumerate(sentences):
        lowered = fold(sentence)
        score = sum(1 for term in terms if term in lowered)
        if score > best_score and sentence:
            best, best_score = sentence, score
            if index + 1 < len(sentences) and len(best) < max_chars // 2:
                best = f"{best} {sentences[index + 1]}"
    if not best:
        best = " ".join(text.split())
    return best[:max_chars]
