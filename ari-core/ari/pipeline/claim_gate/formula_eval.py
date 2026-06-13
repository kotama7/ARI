"""Safe restricted-AST evaluator for DECLARED metric-contract expressions.

Domain-general by construction: it evaluates whatever arithmetic / comparison /
conditional expression the metric_contract DECLARES, over named variables bound
from a config's measured metrics. It has NO domain knowledge — no roofline, no
GFLOP. It is also SAFE: a whitelisted AST walk (never ``eval``/``exec``), so a
declared expression cannot import, call arbitrary functions, or touch attributes.

Supported:
  - numbers, names (bound from ``variables``: scalar or list[float])
  - + - * / and unary - (elementwise when an operand is a list)
  - comparisons < <= > >= == !=  (elementwise on lists -> all(...) -> bool)
  - boolean and/or/not
  - conditional ``A if cond else B`` (for regime ceiling selection)
  - whitelisted reducers: geomean, mean, sum, min, max, abs, sqrt

Returns float | list[float] | bool | None (None on any unsupported node, unknown
name, or undefined op — callers treat None as "could not evaluate").
"""

from __future__ import annotations

import ast
import math
from typing import Any


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _as_list(x: Any) -> "list | None":
    if isinstance(x, list) and all(_is_num(e) for e in x):
        return [float(e) for e in x]
    return None


def _geomean(xs: list) -> "float | None":
    xs = [float(x) for x in xs]
    if not xs or any(x <= 0 for x in xs):
        return None
    return math.exp(sum(math.log(x) for x in xs) / len(xs))


_REDUCERS = {
    "geomean": _geomean,
    "mean": lambda xs: sum(xs) / len(xs) if xs else None,
    "sum": lambda xs: float(sum(xs)),
    "min": lambda xs: float(min(xs)) if xs else None,
    "max": lambda xs: float(max(xs)) if xs else None,
}
_UNARY_FUNCS = {"abs": abs, "sqrt": lambda v: math.sqrt(v) if v >= 0 else None}


def _binop(op: ast.operator, a: Any, b: Any) -> Any:
    la, lb = _as_list(a), _as_list(b)
    if la is not None or lb is not None:
        # broadcast scalar against list, elementwise on equal-length lists
        if la is None:
            la = [a] * len(lb)
        if lb is None:
            lb = [b] * len(la)
        if len(la) != len(lb):
            return None
        return [_binop(op, x, y) for x, y in zip(la, lb)]
    if not (_is_num(a) and _is_num(b)):
        return None
    if isinstance(op, ast.Add):
        return a + b
    if isinstance(op, ast.Sub):
        return a - b
    if isinstance(op, ast.Mult):
        return a * b
    if isinstance(op, ast.Div):
        return a / b if b != 0 else None
    return None


def _compare(op: ast.cmpop, a: float, b: float) -> "bool | None":
    if a is None or b is None:
        return None
    if isinstance(op, ast.Lt):
        return a < b
    if isinstance(op, ast.LtE):
        return a <= b
    if isinstance(op, ast.Gt):
        return a > b
    if isinstance(op, ast.GtE):
        return a >= b
    if isinstance(op, ast.Eq):
        return a == b
    if isinstance(op, ast.NotEq):
        return a != b
    return None


def _eval(node: ast.AST, variables: dict) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body, variables)
    if isinstance(node, ast.Constant):
        return node.value if _is_num(node.value) else None
    if isinstance(node, ast.Name):
        return variables.get(node.id)
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, variables)
        if isinstance(node.op, ast.USub):
            lv = _as_list(v)
            if lv is not None:
                return [-x for x in lv]
            return -v if _is_num(v) else None
        if isinstance(node.op, ast.Not):
            return (not v) if isinstance(v, bool) else None
        return None
    if isinstance(node, ast.BinOp):
        return _binop(node.op, _eval(node.left, variables), _eval(node.right, variables))
    if isinstance(node, ast.BoolOp):
        vals = [_eval(v, variables) for v in node.values]
        if any(not isinstance(v, bool) for v in vals):
            return None
        return all(vals) if isinstance(node.op, ast.And) else any(vals)
    if isinstance(node, ast.Compare):
        # elementwise on lists -> all(); chained comparisons supported
        left = _eval(node.left, variables)
        result = True
        for op, comp in zip(node.ops, node.comparators):
            right = _eval(comp, variables)
            ll, rl = _as_list(left), _as_list(right)
            if ll is not None or rl is not None:
                if ll is None:
                    ll = [left] * len(rl)
                if rl is None:
                    rl = [right] * len(ll)
                if len(ll) != len(rl):
                    return None
                pair_results = [_compare(op, x, y) for x, y in zip(ll, rl)]
                if any(r is None for r in pair_results):
                    return None
                ok = all(pair_results)
            else:
                ok = _compare(op, left, right)
                if ok is None:
                    return None
            result = result and ok
            left = right
        return result
    if isinstance(node, ast.IfExp):
        cond = _eval(node.test, variables)
        if not isinstance(cond, bool):
            return None
        return _eval(node.body if cond else node.orelse, variables)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.keywords:
            return None
        fname = node.func.id
        args = [_eval(a, variables) for a in node.args]
        if fname in _REDUCERS:
            if len(args) == 1:
                xs = _as_list(args[0])
            else:
                xs = [a for a in args if _is_num(a)]
                if len(xs) != len(args):
                    xs = None
            return _REDUCERS[fname](xs) if xs is not None else None
        if fname in _UNARY_FUNCS and len(args) == 1 and _is_num(args[0]):
            return _UNARY_FUNCS[fname](args[0])
        return None
    if isinstance(node, ast.List):
        elts = [_eval(e, variables) for e in node.elts]
        return elts if all(_is_num(e) for e in elts) else None
    return None  # any other node type is unsupported -> not evaluable


def safe_eval(expr: str, variables: dict) -> Any:
    """Evaluate a declared expression over ``variables``. Returns None on parse
    error or any unsupported/unknown construct (never raises on a bad expr)."""
    if not isinstance(expr, str) or not expr.strip():
        return None
    try:
        tree = ast.parse(expr, mode="eval")
    except (SyntaxError, ValueError):
        return None
    try:
        return _eval(tree, variables)
    except Exception:
        return None
