"""Safe predicate evaluator for KB rule conditions.

Conditions are stored as strings like ``"days_since_delivery <= 30 and final_sale == False"``.
We evaluate them against a facts dict WITHOUT Python's ``eval`` — a restricted AST walker
that only permits boolean/comparison/unary ops and literal/name leaves. A referenced fact
that is absent or None raises :class:`MissingFact`, which is how "unanswerable" is detected
mechanically (a rule whose facts aren't available simply cannot fire).
"""
from __future__ import annotations

import ast
import operator

_CMP = {
    ast.Lt: operator.lt, ast.LtE: operator.le,
    ast.Gt: operator.gt, ast.GtE: operator.ge,
    ast.Eq: operator.eq, ast.NotEq: operator.ne,
}
_CONST_NAMES = {"True": True, "False": False, "None": None}


class MissingFact(Exception):
    """Raised when a condition references a fact that is absent/None."""


def evaluate(expr: str, facts: dict) -> bool:
    """Evaluate a condition string against facts. Raises MissingFact on absent inputs."""
    return bool(_ev(ast.parse(expr, mode="eval").body, facts))


def _ev(node, facts):
    if isinstance(node, ast.BoolOp):
        vals = [_ev(v, facts) for v in node.values]
        return all(vals) if isinstance(node.op, ast.And) else any(vals)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _ev(node.operand, facts)
    if isinstance(node, ast.Compare):
        left = _ev(node.left, facts)
        for op, comp in zip(node.ops, node.comparators):
            right = _ev(comp, facts)
            if type(op) not in _CMP:
                raise ValueError(f"operator not allowed: {type(op).__name__}")
            if not _CMP[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Name):
        if node.id in _CONST_NAMES:
            return _CONST_NAMES[node.id]
        if node.id not in facts or facts[node.id] is None:
            raise MissingFact(node.id)
        return facts[node.id]
    if isinstance(node, ast.Constant):
        return node.value
    raise ValueError(f"unsupported expression node: {type(node).__name__}")
