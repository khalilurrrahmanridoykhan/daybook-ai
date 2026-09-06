"""A tiny, explicit tool registry -- each tool is a plain Python function
plus a JSON-Schema description Ollama presents to the model for function
calling. No dynamic discovery or decorator magic: adding a tool means
adding one entry below, so the full set of things the model can actually
do is always visible in one place.
"""

from __future__ import annotations

import ast
import operator
from datetime import datetime, timezone
from typing import Any, Callable

_SAFE_OPS: dict[type, Callable[..., float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.Mod: operator.mod,
}


class ToolError(RuntimeError):
    """Raised for a bad tool name or arguments the model provided -- sent
    back to the model as a tool result so it can react, never raised as
    an unhandled 500."""


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_safe_eval(node.operand))
    raise ToolError(f"Unsupported expression: {ast.dump(node)}")


def calculate(expression: str) -> dict[str, Any]:
    """Evaluates a basic arithmetic expression (+ - * / ** %) via an AST
    whitelist, not Python's real eval() -- so a tool call can't be used to
    smuggle arbitrary code execution."""
    try:
        tree = ast.parse(expression, mode="eval")
        result = _safe_eval(tree.body)
    except (SyntaxError, ToolError, ZeroDivisionError, TypeError) as e:
        raise ToolError(f"Could not evaluate '{expression}': {e}") from e
    return {"expression": expression, "result": result}


def current_datetime() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {"iso": now.isoformat(), "utc": True}


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate a basic arithmetic expression (+, -, *, /, **, %).",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string", "description": "e.g. '12 * (4 + 1)'"}},
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "current_datetime",
            "description": "Get the current date and time in UTC.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

TOOL_FUNCTIONS: dict[str, Callable[..., dict[str, Any]]] = {
    "calculate": calculate,
    "current_datetime": current_datetime,
}


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        raise ToolError(f"Unknown tool: {name}")
    return func(**arguments)
