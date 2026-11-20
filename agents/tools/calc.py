"""Outil de calcul : evaluateur arithmetique sur AST, **sans eval()**.

``eval()`` sur une chaine proposee par un modele est une execution de code
arbitraire. Ici, seuls les noeuds d'une liste blanche sont acceptes, la
profondeur d'expression est bornee et les exposants sont plafonnes pour eviter
un deni de service (``9**9**9``).
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

from agents.core.errors import PolicyError, ToolError

MAX_EXPRESSION_LENGTH = 300
MAX_DEPTH = 24
MAX_EXPONENT = 512
MAX_ABS_RESULT = 1e100

_BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}

_FUNCTIONS: dict[str, Any] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "exp": math.exp,
    "floor": math.floor,
    "ceil": math.ceil,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "hypot": math.hypot,
    "degrees": math.degrees,
    "radians": math.radians,
    "trunc": math.trunc,
}

_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf}


def safe_eval(expression: str, *, max_depth: int = MAX_DEPTH) -> float:
    """Evalue une expression arithmetique pure.

    Leve :class:`PolicyError` si l'expression sort du perimetre autorise et
    :class:`ToolError` si elle est mathematiquement invalide.
    """
    if not isinstance(expression, str):
        raise ToolError("l'expression doit etre une chaine")
    source = expression.strip()
    if not source:
        raise ToolError("expression vide")
    if len(source) > MAX_EXPRESSION_LENGTH:
        raise PolicyError(
            f"expression trop longue ({len(source)} > {MAX_EXPRESSION_LENGTH})",
            hint="decouper le calcul en plusieurs appels",
        )
    # Le symbole ^ est compris comme puissance par les utilisateurs, pas comme XOR.
    source = source.replace("^", "**")
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise ToolError(f"expression invalide: {exc.msg}") from exc
    return _eval_node(tree.body, depth=0, max_depth=max_depth)


def _eval_node(node: ast.AST, *, depth: int, max_depth: int) -> float:
    if depth > max_depth:
        raise PolicyError(
            f"expression trop profonde (> {max_depth})",
            hint="simplifier l'expression",
        )

    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise PolicyError(
                f"litteral non numerique refuse: {node.value!r}",
                hint="seuls les nombres sont acceptes",
            )
        return _check_finite(float(node.value))

    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _BINARY_OPS:
            raise PolicyError(
                f"operateur refuse: {op_type.__name__}",
                hint="operateurs acceptes: + - * / // % **",
            )
        left = _eval_node(node.left, depth=depth + 1, max_depth=max_depth)
        right = _eval_node(node.right, depth=depth + 1, max_depth=max_depth)
        if op_type is ast.Pow:
            if abs(right) > MAX_EXPONENT:
                raise PolicyError(
                    f"exposant trop grand ({right})",
                    hint=f"exposant limite a {MAX_EXPONENT}",
                )
            if abs(left) > 1e6 and abs(right) > 10:
                raise PolicyError("base et exposant trop grands : resultat non calculable")
        try:
            result = _BINARY_OPS[op_type](left, right)
        except ZeroDivisionError as exc:
            raise ToolError("division par zero") from exc
        except OverflowError as exc:
            raise ToolError("depassement de capacite numerique") from exc
        return _check_finite(float(result))

    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _UNARY_OPS:
            raise PolicyError(f"operateur unaire refuse: {op_type.__name__}")
        value = _eval_node(node.operand, depth=depth + 1, max_depth=max_depth)
        return _check_finite(float(_UNARY_OPS[op_type](value)))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            raise PolicyError(
                "appel de fonction refuse",
                hint=f"fonctions autorisees: {', '.join(sorted(_FUNCTIONS))}",
            )
        if node.keywords:
            raise PolicyError("les arguments nommes sont refuses")
        args = [_eval_node(arg, depth=depth + 1, max_depth=max_depth) for arg in node.args]
        if node.func.id == "round" and len(args) == 2:
            args[1] = int(args[1])  # round(x, ndigits) exige un entier
        try:
            return _check_finite(float(_FUNCTIONS[node.func.id](*args)))
        except (ValueError, TypeError, OverflowError) as exc:
            raise ToolError(f"erreur mathematique dans {node.func.id}(): {exc}") from exc

    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _check_finite(float(_CONSTANTS[node.id]))
        raise PolicyError(
            f"nom inconnu refuse: {node.id}",
            hint=f"constantes acceptees: {', '.join(sorted(_CONSTANTS))}",
        )

    raise PolicyError(
        f"construction Python refusee: {type(node).__name__}",
        hint="seules les operations arithmetiques sont autorisees",
    )


def _check_finite(value: float) -> float:
    if not math.isfinite(value) or abs(value) > MAX_ABS_RESULT:
        raise ToolError(
            "resultat non fini ou hors bornes",
            hint="verifier les operandes (division par zero, exposant geant)",
        )
    return value


def format_number(value: float) -> str:
    """Formate sans bruit flottant inutile (2.0 -> '2', 0.30000000000004 -> arrondi)."""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.10g}"


def evaluate(expression: str) -> str:
    """Fonction d'entree de l'outil ``calc_evaluate``."""
    value = safe_eval(expression)
    return f"{format_number(value)} (expression: {expression}, valeur exacte: {value!r})"
