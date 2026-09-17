"""Calculator tool — evaluates mathematical expressions safely.

Permission level: READ
"""

import ast
import operator
from typing import Any

from app.models.tool_schema import ToolSpec
from app.tools.registry import Tool


# Supported binary operators
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

# Supported unary operators
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _eval_node(node: ast.AST) -> float:
    """Recursively evaluate an AST node safely."""
    if isinstance(node, ast.Constant):  # Python 3.8+
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant: {node.value!r}")
    elif isinstance(node, ast.BinOp):
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        op_func = _BIN_OPS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        return op_func(left, right)
    elif isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand)
        op_func = _UNARY_OPS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
        return op_func(operand)
    elif isinstance(node, ast.Expression):
        return _eval_node(node.body)
    else:
        raise ValueError(f"Unsupported expression element: {type(node).__name__}")


class Calculator(Tool):
    """Safely evaluate a mathematical expression."""

    def __init__(self) -> None:
        super().__init__(
            ToolSpec(
                id="calculator",
                name="Calculator",
                description="Safely evaluate a mathematical expression. Supports +, -, *, /, //, %, **, parentheses. Parameters: expression (str, required).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string", "description": "Mathematical expression to evaluate"},
                    },
                    "required": ["expression"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "result": {"type": "number"},
                        "expression": {"type": "string"},
                    },
                },
                permission_level="READ",
            )
        )

    async def execute(self, **params: Any) -> dict:
        expression = params.get("expression")
        if not expression:
            return {"success": False, "output": None, "error": "Missing required parameter: expression"}

        try:
            tree = ast.parse(expression, mode="eval")
            result = _eval_node(tree)
            return {
                "success": True,
                "output": {
                    "result": result,
                    "expression": expression,
                },
                "error": None,
            }
        except Exception as e:
            return {"success": False, "output": None, "error": f"Calculation error: {e}"}