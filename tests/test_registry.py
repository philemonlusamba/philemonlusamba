"""Tests du registre d'outils : validation, isolation des erreurs, timeouts."""

from __future__ import annotations

import asyncio
import time

import pytest
from agents.core.errors import ToolError, ToolValidationError
from agents.core.registry import ToolRegistry, validate_arguments

SCHEMA = {
    "type": "object",
    "properties": {
        "expression": {"type": "string", "minLength": 1, "maxLength": 20},
        "count": {"type": "integer", "minimum": 1, "maximum": 5},
        "mode": {"type": "string", "enum": ["rapide", "complet"]},
    },
    "required": ["expression"],
    "additionalProperties": False,
}


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        name="echo",
        description="retourne l'expression",
        input_schema=SCHEMA,
        handler=lambda expression, count=1, mode="rapide": f"{expression}x{count}:{mode}",
    )
    return reg


def test_valid_call(registry: ToolRegistry) -> None:
    assert asyncio.run(registry.invoke("echo", {"expression": "2+2"})) == "2+2x1:rapide"


def test_unknown_tool(registry: ToolRegistry) -> None:
    with pytest.raises(ToolError, match="outil inconnu"):
        asyncio.run(registry.invoke("nope", {}))


def test_missing_required_argument(registry: ToolRegistry) -> None:
    with pytest.raises(ToolValidationError, match="manquants"):
        asyncio.run(registry.invoke("echo", {}))


def test_unknown_argument_rejected(registry: ToolRegistry) -> None:
    with pytest.raises(ToolValidationError, match="inconnus"):
        asyncio.run(registry.invoke("echo", {"expression": "a", "injection": "--rm"}))


def test_wrong_type(registry: ToolRegistry) -> None:
    with pytest.raises(ToolValidationError, match="type attendu"):
        asyncio.run(registry.invoke("echo", {"expression": 5}))


def test_bool_is_not_an_integer(registry: ToolRegistry) -> None:
    with pytest.raises(ToolValidationError):
        asyncio.run(registry.invoke("echo", {"expression": "a", "count": True}))


def test_bounds_and_enum(registry: ToolRegistry) -> None:
    with pytest.raises(ToolValidationError, match="maximum"):
        asyncio.run(registry.invoke("echo", {"expression": "a", "count": 9}))
    with pytest.raises(ToolValidationError, match="hors de"):
        asyncio.run(registry.invoke("echo", {"expression": "a", "mode": "turbo"}))
    with pytest.raises(ToolValidationError, match="maxLength"):
        asyncio.run(registry.invoke("echo", {"expression": "a" * 50}))


def test_arguments_must_be_an_object() -> None:
    spec = ToolRegistry()
    spec.register(name="x", description="d", input_schema=SCHEMA, handler=lambda **_: "ok")
    with pytest.raises(ToolValidationError, match="objet JSON"):
        asyncio.run(spec.invoke("x", ["expression"]))  # type: ignore[arg-type]


def test_sync_handler_error_is_wrapped() -> None:
    reg = ToolRegistry()
    reg.register(
        name="boom",
        description="echoue",
        input_schema={"type": "object", "properties": {}},
        handler=lambda: 1 / 0,
    )
    with pytest.raises(ToolError, match="echec de l'outil"):
        asyncio.run(reg.invoke("boom", {}))


def test_async_handler_supported() -> None:
    reg = ToolRegistry()

    async def handler(value: str) -> str:
        return value.upper()

    reg.register(
        name="upper",
        description="majuscules",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        handler=handler,
    )
    assert asyncio.run(reg.invoke("upper", {"value": "ok"})) == "OK"


def test_timeout_on_slow_sync_handler() -> None:
    reg = ToolRegistry()
    reg.register(
        name="lent",
        description="dort",
        input_schema={"type": "object", "properties": {}},
        handler=lambda: time.sleep(0.3),
        timeout_s=0.05,
    )
    with pytest.raises(ToolError, match="timeout"):
        asyncio.run(reg.invoke("lent", {}))


def test_output_is_truncated() -> None:
    reg = ToolRegistry()
    reg.register(
        name="bavard",
        description="long",
        input_schema={"type": "object", "properties": {}},
        handler=lambda: "x" * 500,
        max_output_chars=50,
    )
    output = asyncio.run(reg.invoke("bavard", {}))
    assert "tronquee" in output
    assert len(output) < 150


def test_duplicate_and_invalid_names(registry: ToolRegistry) -> None:
    with pytest.raises(ValueError, match="deja enregistre"):
        registry.register(
            name="echo",
            description="d",
            input_schema={"type": "object", "properties": {}},
            handler=lambda: "x",
        )
    with pytest.raises(ValueError, match="invalide"):
        registry.register(
            name="nom-invalide",
            description="d",
            input_schema={"type": "object", "properties": {}},
            handler=lambda: "x",
        )


def test_schemas_can_be_filtered(registry: ToolRegistry) -> None:
    assert [schema["name"] for schema in registry.schemas()] == ["echo"]
    assert registry.schemas(["echo", "absent"])[0]["name"] == "echo"
    assert registry.schemas(["absent"]) == []


def test_validate_arguments_accepts_defaults_absent(registry: ToolRegistry) -> None:
    validate_arguments(registry.get("echo"), {"expression": "1"})
