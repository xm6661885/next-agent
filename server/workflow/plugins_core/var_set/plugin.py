from server.workflow.engine.variables import coerce, to_text
from server.workflow.sdk import Input, Output, Plugin, StepError

OPS = [
    {"value": "set", "label": "Set to"},
    {"value": "add", "label": "Add (number) / append (text)"},
    {"value": "sub", "label": "Subtract (number)"},
    {"value": "toggle", "label": "Toggle (boolean)"},
]


class SetVariable(Plugin):
    id = "builtin.var_set"
    name = "Set variable"
    icon = "variable"
    color = "purple"
    category = "Variables"
    description = "Changes the value of a named variable"
    inputs = [
        Input("name", "varname", "Variable", required=True),
        Input("op", "select", "Operation", default="set", options=OPS),
        Input("value", "text", "Value", magic=True),
    ]
    outputs = [Output("value", "any", "New value", default=True)]

    async def run(self, ctx, p):
        name = p["name"]
        var = ctx.vars.get(name)
        if var is None:
            raise StepError(f'Variable "{name}" is not defined yet. Add a Define variable card above')
        typ, cur, op = var["type"], var["value"], p["op"] or "set"
        if op == "toggle":
            if typ != "bool":
                raise StepError("Toggle only works on boolean variables")
            new = not cur
        elif op in ("add", "sub"):
            if typ == "number":
                delta = coerce(p["value"], "number", "Value") or 0
                new = (cur or 0) + (delta if op == "add" else -delta)
            elif typ == "text" and op == "add":
                new = to_text(cur) + to_text(p["value"])
            else:
                raise StepError(f"This operation does not work on {typ} variables")
        else:
            new = coerce(p["value"], typ, name)
        var["value"] = new
        return {"value": new}
