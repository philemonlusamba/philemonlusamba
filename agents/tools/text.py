"""Outils de traitement de texte : statistiques et resume extractif.

Le resume est *extractif* (selection de phrases) : aucune generation, donc aucun
risque d'hallucination, et le resultat est deterministe.
"""

from __future__ import annotations

import re
from collections import Counter

from agents.core.errors import ToolError

_WORD_RE = re.compile(r"[\w'À-ÿ-]+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
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
        "il",
        "elle",
        "on",
        "nous",
        "vous",
        "ils",
        "a",
        "d",
        "l",
        "s",
        "ne",
        "pas",
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
)


def stats(text: str) -> str:
    """Statistiques simples d'un texte."""
    if not text.strip():
        raise ToolError("texte vide")
    words = _WORD_RE.findall(text)
    sentences = [s for s in _SENTENCE_RE.split(text) if s.strip()]
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    average = len(words) / len(sentences) if sentences else 0.0
    return (
        f"caracteres={len(text)} mots={len(words)} phrases={len(sentences)} "
        f"paragraphes={len(paragraphs)} mots_par_phrase={average:.1f}"
    )


def summarize(text: str, *, max_sentences: int = 3) -> str:
    """Resume extractif : les phrases les plus riches en mots frequents, dans l'ordre."""
    if not text.strip():
        raise ToolError("texte vide")
    sentences = [s.strip() for s in _SENTENCE_RE.split(text) if len(s.strip()) > 20]
    if not sentences:
        return " ".join(text.split())[:400]

    words = [word.lower() for word in _WORD_RE.findall(text) if word.lower() not in _STOPWORDS]
    frequencies = Counter(words)
    if not frequencies:
        return " ".join(sentences[:max_sentences])

    scored: list[tuple[int, float]] = []
    for index, sentence in enumerate(sentences):
        tokens = [w.lower() for w in _WORD_RE.findall(sentence) if w.lower() not in _STOPWORDS]
        if not tokens:
            continue
        score = sum(frequencies[token] for token in tokens) / (len(tokens) ** 0.6)
        scored.append((index, score))

    best = sorted(scored, key=lambda item: (-item[1], item[0]))[: max(1, max_sentences)]
    ordered = [sentences[index] for index, _ in sorted(best)]
    return " ".join(ordered)[:1200]
