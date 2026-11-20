"""Extraction tolerante de JSON depuis une sortie de modele.

Les LLM encadrent souvent leur JSON de texte, de balises ```json, ou laissent une
virgule finale. Plutot que de faire confiance a ``json.loads`` (qui echoue dans
tous ces cas), on isole le premier objet equilibre, en respectant les chaines et
les echappements.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.S)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _balanced_object(text: str) -> str | None:
    """Retourne le premier objet JSON equilibre de ``text``, ou ``None``."""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        start = text.find("{", start + 1)
    return None


def extract_json_object(text: str) -> dict[str, Any]:
    """Extrait un objet JSON d'une sortie de modele.

    Leve :class:`ValueError` si aucun objet exploitable n'est trouve.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("sortie vide : aucun JSON a extraire")

    candidates: list[str] = []
    stripped = text.strip()
    candidates.append(stripped)
    candidates.extend(match.group(1).strip() for match in _FENCE_RE.finditer(text))
    balanced = _balanced_object(stripped)
    if balanced:
        candidates.append(balanced)

    for candidate in candidates:
        for variant in (candidate, _TRAILING_COMMA_RE.sub(r"\1", candidate)):
            try:
                parsed = json.loads(variant)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    raise ValueError(
        f"aucun objet JSON valide dans la sortie du modele (debut: {stripped[:120]!r})"
    )


def as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []
