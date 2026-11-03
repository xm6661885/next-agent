"""Magic variables: token array parsing, scope validation and type coercion.

Text is stored as a token array: ["Summarize: ", {"ref": "b1", "field": "result"}, "\\nBe concise"]
Special sources: @input (workflow inputs), @env (global environment variables), @loop (item/index inside a loop),
@var (named variables created by the Define variable card).
Optional token fields: field (output field, defaults to the default one), path (keys to keep drilling into a dict/list), loop (which loop).
"""
import json
from typing import Any

from ..sdk import StepError

SPECIAL = {"@input", "@env", "@loop", "@var"}
LOOP_TYPES = {"core.repeat", "core.repeat_each"}


def is_ref(t: Any) -> bool:
    return isinstance(t, dict) and isinstance(t.get("ref"), str)


def to_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def truthy(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() not in ("", "false", "0", "no", "none", "null")
    return bool(v)


class Scope:
    """Variable space of one workflow run (a sub-workflow has its own Scope)."""

    def __init__(self, inputs: dict, env: dict):
        self.inputs = inputs
        self.env = env
        self.outputs: dict[str, dict] = {}  # block_id -> {"fields": {}, "default": name}
        self.loops: list[dict] = []  # [{"id":..., "item":..., "index":...}]
        self.vars: dict[str, dict] = {}  # name -> {"type": text|number|bool, "value": ...}

    def lookup(self, tok: dict) -> Any:
        ref = tok["ref"]
        field = tok.get("field")
        if ref == "@input":
            val = self.inputs.get(field)
        elif ref == "@env":
            val = self.env.get(field, "")
        elif ref == "@var":
            if field not in self.vars:
                raise StepError(f'Variable "{field}" is not defined yet. Add a Define variable card above')
            val = self.vars[field]["value"]
        elif ref == "@loop":
            frame = None
            if tok.get("loop"):
                frame = next((f for f in reversed(self.loops) if f["id"] == tok["loop"]), None)
            elif self.loops:
                frame = self.loops[-1]
            if frame is None:
                raise StepError("Repeat Item and Repeat Index can only be used inside a Repeat card")
            val = frame.get(field or "item")
        else:
            out = self.outputs.get(ref)
            if out is None:
                raise StepError(f"The referenced card ({ref}) has no output yet. Check that it is above this card")
            val = out["fields"].get(field or out["default"])
        for key in tok.get("path") or []:
            val = _drill(val, key)
        return val


def _drill(val: Any, key: Any) -> Any:
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except ValueError:
            return None
    if isinstance(val, dict):
        return val.get(str(key))
    if isinstance(val, list):
        try:
            return val[int(key)]
        except (ValueError, IndexError):
            return None
    return None


def resolve_text(tokens: Any, scope: Scope) -> str:
    if not isinstance(tokens, list):
        return to_text(tokens)
    return "".join(to_text(scope.lookup(t)) if is_ref(t) else to_text(t) for t in tokens)


def resolve_value(tokens: Any, scope: Scope) -> Any:
    """Keeps the original type when there is a single variable token, otherwise joins into text."""
    if not isinstance(tokens, list):
        return tokens
    parts = [t for t in tokens if not (isinstance(t, str) and t == "")]
    if len(parts) == 1 and is_ref(parts[0]):
        return scope.lookup(parts[0])
    return resolve_text(tokens, scope)


def coerce(value: Any, typ: str, label: str = "") -> Any:
    where = f'"{label}"' if label else "Value"
    if typ in ("text", "code", "select", "workflow", "agent", "acp_agent", "expr", "varname"):
        return to_text(value)
    if typ == "number":
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return value
        s = to_text(value).strip()
        if s == "":
            return None
        try:
            return int(s)
        except ValueError:
            try:
                return float(s)
            except ValueError:
                raise StepError(f"{where} is not a valid number: {s[:40]}") from None
    if typ == "bool":
        return truthy(value)
    if typ == "any":
        return value
    if typ == "json":
        if isinstance(value, str):
            s = value.strip()
            if s == "":
                return None
            try:
                return json.loads(s)
            except ValueError as e:
                raise StepError(f"{where} is not valid JSON: {e}") from None
        return value
    if typ == "list":
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            s = value.strip()
            if s.startswith("["):
                try:
                    v = json.loads(s)
                    if isinstance(v, list):
                        return v
                except ValueError:
                    pass
            return [ln for ln in s.splitlines() if ln.strip() != ""]
        if isinstance(value, dict):
            return list(value.values())
        return [value]
    return value


def resolve_params(inputs: list, params: dict, scope: Scope) -> dict:
    """Resolves a card's parameters from the plugin schema. inputs is a list of sdk.Input."""
    out = {}
    for inp in inputs:
        raw = params.get(inp.name, inp.default)
        if inp.magic and isinstance(raw, list):
            raw = resolve_value(raw, scope) if inp.type in ("json", "list", "number", "bool", "any") else resolve_text(raw, scope)
        val = coerce(raw, inp.type, inp.label or inp.name)
        if inp.required and (val is None or val == ""):
            raise StepError(f"Missing required parameter \"{inp.label or inp.name}\"")
        out[inp.name] = val
    return out


def iter_tokens(obj: Any):
    """Recursively finds all variable tokens in an object."""
    if is_ref(obj):
        yield obj
    elif isinstance(obj, list):
        for x in obj:
            yield from iter_tokens(x)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from iter_tokens(v)


def branches_of(block: dict) -> list[str]:
    t = block.get("type")
    if t == "core.if":
        return ["then", "else"]
    if t in LOOP_TYPES:
        return ["body"]
    return []


def find_invalid_refs(blocks: list, visible: set | None = None, loops: tuple = ()) -> list[dict]:
    """Finds tokens that reference cards which are not visible above."""
    visible = visible or set()
    problems: list[dict] = []
    local: set[str] = set()
    for b in blocks:
        avail = visible | local
        for tok in iter_tokens(b.get("params") or {}):
            ref = tok["ref"]
            if ref in ("@input", "@env", "@var"):
                continue
            if ref == "@loop":
                if not loops or (tok.get("loop") and tok["loop"] not in loops):
                    problems.append({"block_id": b["id"], "ref": ref, "reason": "not inside a Repeat card"})
            elif ref not in avail:
                problems.append({"block_id": b["id"], "ref": ref, "reason": "the referenced card does not exist or is below"})
        inner_loops = loops + ((b["id"],) if b.get("type") in LOOP_TYPES else ())
        for br in branches_of(b):
            problems += find_invalid_refs(b.get(br) or [], avail, inner_loops)
        local.add(b["id"])
    return problems


# ---------------------------------------------------------------- Flat <-> tree
# Workflows are stored as a flat list (like iOS Shortcuts). Control flow is written as marker cards
# that share a "group" with their opening card:
#   core.if ... core.else ... core.end_if          (core.else is optional)
#   core.repeat / core.repeat_each ... core.end_repeat
# build_tree() turns that into the nested form the engine runs: if -> then/else, loops -> body.
MARKERS = {"core.else", "core.end_if", "core.end_repeat"}
OPENERS = {"core.if": "core.end_if", "core.repeat": "core.end_repeat", "core.repeat_each": "core.end_repeat"}


def build_tree(blocks: list) -> list:
    if is_nested(blocks):  # hand-written / imported definitions may use the nested form
        blocks = flatten(blocks)
    root: list = []
    stack: list[tuple[dict, list]] = []  # (opening node, list currently being filled)

    def target() -> list:
        return stack[-1][1] if stack else root

    for b in blocks:
        t = b.get("type")
        if t in OPENERS:
            node = {**b}
            for k in ("then", "else", "body"):
                node.pop(k, None)
            if t == "core.if":
                node["then"], node["else"] = [], []
                inner = node["then"]
            else:
                node["body"] = []
                inner = node["body"]
            target().append(node)
            stack.append((node, inner))
        elif t in MARKERS:
            if not stack or stack[-1][0]["id"] != b.get("group"):
                raise StepError(f'Control flow is unbalanced: "{t}" has no matching opening card. Fix the order in the editor')
            node = stack[-1][0]
            if t == "core.else":
                if node["type"] != "core.if":
                    raise StepError("Otherwise must belong to an If card")
                stack[-1] = (node, node["else"])
            else:
                if OPENERS[node["type"]] != t:
                    raise StepError("Control flow is unbalanced: End card does not match")
                stack.pop()
        else:
            target().append(b)
    if stack:
        raise StepError(f'Control flow is unbalanced: "{stack[-1][0]["type"]}" has no End card')
    return root


def flatten(blocks: list) -> list:
    """Inverse of build_tree: nested if/repeat (old format) -> flat list with marker cards."""
    out = []
    for b in blocks:
        t = b.get("type")
        if t not in OPENERS:
            out.append(b)
            continue
        head = {k: v for k, v in b.items() if k not in ("then", "else", "body")}
        out.append(head)
        if t == "core.if":
            out += flatten(b.get("then") or [])
            if b.get("else"):
                out.append({"id": b["id"] + "e", "type": "core.else", "group": b["id"]})
                out += flatten(b["else"])
            out.append({"id": b["id"] + "z", "type": "core.end_if", "group": b["id"]})
        else:
            out += flatten(b.get("body") or [])
            out.append({"id": b["id"] + "z", "type": "core.end_repeat", "group": b["id"]})
    return out


def is_nested(blocks: list) -> bool:
    return any(b.get("type") in OPENERS and any(k in b for k in ("then", "else", "body")) for b in blocks)
