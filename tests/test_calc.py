"""Tests de l'evaluateur arithmetique : correction **et** confinement."""

from __future__ import annotations

import pytest
from agents.core.errors import PolicyError, ToolError
from agents.tools.calc import evaluate, format_number, safe_eval


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("2+3*4", 14.0),
        ("(2+3)*4", 20.0),
        ("10/4", 2.5),
        ("10//3", 3.0),
        ("10%3", 1.0),
        ("2^10", 1024.0),  # ^ est traite comme puissance, pas comme XOR
        ("-5 + 3", -2.0),
        ("sqrt(16)", 4.0),
        ("round(2.567, 2)", 2.57),
        ("max(1, 9, 3)", 9.0),
        ("pi", pytest.approx(3.14159, rel=1e-4)),
        ("hypot(3, 4)", 5.0),
    ],
)
def test_safe_eval_computes(expression: str, expected: float) -> None:
    assert safe_eval(expression) == pytest.approx(expected)


@pytest.mark.parametrize(
    "malicious",
    [
        "__import__('os').system('echo hacked')",
        "open('/etc/passwd').read()",
        "(1).__class__.__bases__",
        "[x for x in range(3)]",
        "(lambda: 42)()",
        "exec('1+1')",
        "'abc' * 3",
        "x + 1",
    ],
)
def test_safe_eval_refuses_code_execution(malicious: str) -> None:
    with pytest.raises((PolicyError, ToolError)):
        safe_eval(malicious)


def test_safe_eval_blocks_huge_exponent() -> None:
    with pytest.raises(PolicyError, match="exposant"):
        safe_eval("9**9999")


def test_safe_eval_blocks_stacked_exponent() -> None:
    with pytest.raises((PolicyError, ToolError)):
        safe_eval("9**9**9")


def test_safe_eval_blocks_long_expression() -> None:
    with pytest.raises(PolicyError, match="trop longue"):
        safe_eval("1+" * 200 + "1")


def test_safe_eval_blocks_deep_unary_nesting() -> None:
    with pytest.raises(PolicyError, match="profonde"):
        safe_eval("-" * 60 + "1")


def test_parentheses_do_not_count_as_depth() -> None:
    assert safe_eval("(" * 30 + "7" + ")" * 30) == 7.0


def test_division_by_zero_is_a_tool_error() -> None:
    with pytest.raises(ToolError, match="division par zero"):
        safe_eval("1/0")


def test_domain_error_is_a_tool_error() -> None:
    with pytest.raises(ToolError):
        safe_eval("sqrt(-1)")


def test_empty_expression_rejected() -> None:
    with pytest.raises(ToolError):
        safe_eval("   ")


def test_result_must_be_finite() -> None:
    with pytest.raises(ToolError):
        safe_eval("10**400")


def test_format_number_hides_float_noise() -> None:
    assert format_number(2.0) == "2"
    assert format_number(2999.8799999999997) == "2999.88"


def test_evaluate_reports_expression() -> None:
    output = evaluate("12*249.99")
    assert "2999.88" in output
    assert "12*249.99" in output
