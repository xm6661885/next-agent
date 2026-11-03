"""Branch condition: Python-style expressions evaluated in a restricted way with simpleeval.

The expression is stored as a token array. Variable tokens are replaced with v1, v2... before evaluation and bound to the real values (types preserved).
"""
from typing import Any

from simpleeval import EvalWithCompoundTypes

from ..sdk import StepError
from .variables import Scope, is_ref

FUNCTIONS = {
    "len": len,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
    "round": round,
    "sorted": sorted,
    "any": any,
    "all": all,
    "list": list,
}
CONSTANTS = {"true": True, "false": False, "null": None, "none": None}


def evaluate(tokens: Any, scope: Scope) -> Any:
    names: dict[str, Any] = {}
    seen: dict[str, str] = {}
    parts: list[str] = []
    for t in tokens if isinstance(tokens, list) else [tokens]:
        if is_ref(t):
            key = repr(sorted((k, str(v)) for k, v in t.items()))
            if key not in seen:
                seen[key] = f"v{len(seen) + 1}"
                names[seen[key]] = scope.lookup(t)
            parts.append(seen[key])
        else:
            parts.append("" if t is None else str(t))
    expr = "".join(parts).strip()
    if not expr:
        raise StepError("The condition expression is empty")
    ev = EvalWithCompoundTypes(names={**CONSTANTS, **names}, functions=FUNCTIONS)
    try:
        return ev.eval(expr)
    except Exception as e:  # noqa: BLE001 - simpleeval raises many kinds of exceptions; convert them all to a readable error
        raise StepError(f"Condition expression error: {e} ({expr})") from None
