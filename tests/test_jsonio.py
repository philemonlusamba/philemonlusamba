"""Tests de l'extraction JSON tolerante (sorties de modele imparfaites)."""

from __future__ import annotations

import pytest
from agents.core.jsonio import as_float, as_int, as_str_list, extract_json_object


@pytest.mark.parametrize(
    "text",
    [
        '{"tasks": [{"id": "t1"}]}',
        '```json\n{"tasks": [{"id": "t1"}]}\n```',
        '```\n{"tasks": [{"id": "t1"}]}\n```',
        'Voici le plan :\n{"tasks": [{"id": "t1"}]}\nBonne chance.',
        '{"tasks": [{"id": "t1"},]}',
        'Préambule\n```json\n{"tasks": [{"id": "t1"}],}\n```\nfin',
    ],
)
def test_extracts_object(text: str) -> None:
    assert extract_json_object(text)["tasks"][0]["id"] == "t1"


def test_braces_inside_strings_are_not_confused() -> None:
    payload = '{"instruction": "utilise {ceci} et {cela}", "id": "t1"}'
    assert extract_json_object(payload)["id"] == "t1"


def test_nested_objects_are_kept() -> None:
    text = 'texte {"a": {"b": {"c": 1}}} suite'
    assert extract_json_object(text)["a"]["b"]["c"] == 1


@pytest.mark.parametrize("text", ["", "   ", "aucun json ici", "[1, 2, 3]", "{{{"])
def test_invalid_input_raises(text: str) -> None:
    with pytest.raises(ValueError):
        extract_json_object(text)


def test_helpers_are_tolerant() -> None:
    assert as_float("0.8", 0.5) == 0.8
    assert as_float(None, 0.5) == 0.5
    assert as_float("abc", 0.5) == 0.5
    assert as_int("3", 1) == 3
    assert as_int("x", 1) == 1
    assert as_str_list(["a", " b ", ""]) == ["a", "b"]
    assert as_str_list("a") == ["a"]
    assert as_str_list(None) == []
    assert as_str_list(42) == []
