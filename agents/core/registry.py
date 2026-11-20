"""Registre d'outils : declaration, validation des arguments, execution isolee.

Trois garanties recherchees ici, parce qu'un outil est la surface d'attaque
principale d'un agent :

1. **validation stricte** des arguments contre un schema JSON minimal avant tout
   appel (une cle inconnue est rejetee, pas ignoree) ;
2. **timeout** systematique, y compris pour les handlers synchrones qui sinon
   bloqueraient la boucle d'evenements ;
3. **sortie bornee** pour eviter de saturer le contexte du modele.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from agents.core.errors import AgentError, ToolError, ToolValidationError

_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list, tuple),
    "object": (dict,),
}


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Declaration d'un outil exposable au modele."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Any]
    timeout_s: float = 10.0
    max_output_chars: int = 4000

    def neutral_schema(self) -> dict[str, Any]:
        """Forme neutre convertie par chaque provider."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


def _type_error(name: str, arg: str, expected: str, value: Any) -> ToolValidationError:
    return ToolValidationError(
        f"argument {arg!r} de l'outil {name!r}: type attendu {expected}, "
        f"recu {type(value).__name__}",
        hint="corriger l'appel: le schema de l'outil est dans le prompt systeme",
    )


def validate_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> None:
    """Verifie un appel d'outil ; leve :class:`ToolValidationError` si invalide."""
    if not isinstance(arguments, dict):
        raise ToolValidationError(
            f"les arguments de {spec.name!r} doivent etre un objet JSON",
            hint='exemple: {"expression": "2+2"}',
        )
    schema = spec.input_schema or {}
    properties: dict[str, Any] = schema.get("properties", {}) or {}
    required: list[str] = list(schema.get("required", []) or [])

    missing = [name for name in required if name not in arguments]
    if missing:
        raise ToolValidationError(
            f"arguments manquants pour {spec.name!r}: {', '.join(missing)}",
            hint=f"parametres attendus: {', '.join(properties) or 'aucun'}",
        )

    unknown = [name for name in arguments if name not in properties]
    if unknown and schema.get("additionalProperties", False) is False:
        raise ToolValidationError(
            f"arguments inconnus pour {spec.name!r}: {', '.join(map(str, unknown))}",
            hint=f"parametres acceptes: {', '.join(properties) or 'aucun'}",
        )

    for name, value in arguments.items():
        rules = properties.get(name) or {}
        expected = rules.get("type")
        if expected in _JSON_TYPES:
            allowed = _JSON_TYPES[expected]
            if isinstance(value, bool) and expected in {"integer", "number"}:
                raise _type_error(spec.name, name, expected, value)
            if not isinstance(value, allowed):
                raise _type_error(spec.name, name, expected, value)
        enum = rules.get("enum")
        if enum is not None and value not in enum:
            raise ToolValidationError(
                f"argument {name!r} de {spec.name!r}: valeur {value!r} hors de {enum}",
            )
        if isinstance(value, str):
            if "maxLength" in rules and len(value) > rules["maxLength"]:
                raise ToolValidationError(
                    f"argument {name!r} de {spec.name!r}: {len(value)} caracteres > "
                    f"maxLength={rules['maxLength']}",
                )
            if "minLength" in rules and len(value) < rules["minLength"]:
                raise ToolValidationError(
                    f"argument {name!r} de {spec.name!r}: trop court "
                    f"(minLength={rules['minLength']})",
                )
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in rules and value < rules["minimum"]:
                raise ToolValidationError(
                    f"argument {name!r} de {spec.name!r}: {value} < minimum {rules['minimum']}",
                )
            if "maximum" in rules and value > rules["maximum"]:
                raise ToolValidationError(
                    f"argument {name!r} de {spec.name!r}: {value} > maximum {rules['maximum']}",
                )


@dataclass
class ToolRegistry:
    """Collection d'outils indexes par nom."""

    default_timeout_s: float = 10.0
    _tools: dict[str, ToolSpec] = field(default_factory=dict)

    def register(
        self,
        *,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: Callable[..., Any],
        timeout_s: float | None = None,
        max_output_chars: int = 4000,
    ) -> ToolSpec:
        if not name or not name.replace("_", "").isalnum():
            raise ValueError(f"nom d'outil invalide: {name!r} (snake_case attendu)")
        if name in self._tools:
            raise ValueError(f"outil deja enregistre: {name!r}")
        spec = ToolSpec(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
            timeout_s=self.default_timeout_s if timeout_s is None else timeout_s,
            max_output_chars=max_output_chars,
        )
        self._tools[name] = spec
        return spec

    def tool(
        self,
        *,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        timeout_s: float | None = None,
        max_output_chars: int = 4000,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorateur d'enregistrement."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.register(
                name=name,
                description=description,
                input_schema=input_schema,
                handler=func,
                timeout_s=timeout_s,
                max_output_chars=max_output_chars,
            )
            return func

        return decorator

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolError(
                f"outil inconnu: {name!r}",
                hint=f"outils disponibles: {', '.join(self.names()) or 'aucun'}",
            ) from exc

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[ToolSpec]:
        return [self._tools[name] for name in self.names()]

    def schemas(self, allowed: Sequence[str] | None = None) -> list[dict[str, Any]]:
        """Schemas neutres, restreints a ``allowed`` si fourni."""
        if allowed is None:
            return [spec.neutral_schema() for spec in self.specs()]
        selected = [self._tools[name] for name in dict.fromkeys(allowed) if name in self._tools]
        return [spec.neutral_schema() for spec in selected]

    async def invoke(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout_s: float | None = None,
    ) -> str:
        """Execute un outil et retourne sa sortie texte (jamais d'exception brute)."""
        spec = self.get(name)
        args = {} if arguments is None else arguments
        validate_arguments(spec, args)
        effective_timeout = spec.timeout_s if timeout_s is None else timeout_s

        try:
            if inspect.iscoroutinefunction(spec.handler):
                result = await asyncio.wait_for(spec.handler(**args), timeout=effective_timeout)
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(spec.handler, **args), timeout=effective_timeout
                )
        except TimeoutError as exc:
            raise ToolError(
                f"timeout de l'outil {name!r} apres {effective_timeout:.1f}s",
                hint="reduire la charge de l'outil ou augmenter son timeout",
            ) from exc
        except AgentError:
            # Erreur deja explicite (policy, timeout d'outil, budget) : on la laisse
            # remonter telle quelle, sinon le message utile serait noye.
            raise
        except Exception as exc:
            raise ToolError(
                f"echec de l'outil {name!r}: {type(exc).__name__}: {exc}",
                hint="verifier les arguments et l'environnement de l'outil",
            ) from exc

        return self._stringify(result, spec.max_output_chars)

    @staticmethod
    def _stringify(result: Any, max_chars: int) -> str:
        if result is None:
            return ""
        text = result if isinstance(result, str) else str(result)
        if len(text) > max_chars:
            removed = len(text) - max_chars
            return f"{text[:max_chars]}\n...[sortie tronquee: {removed} caracteres retires]"
        return text
