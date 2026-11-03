from server.workflow.engine.variables import coerce
from server.workflow.sdk import Input, Output, Plugin, StepError

VAR_TYPES = [{"value": "text", "label": "Text"}, {"value": "number", "label": "Number"}, {"value": "bool", "label": "Boolean"}]


def check_name(name: str) -> str:
    name = (name or "").strip()
    if not name or not name.replace("_", "").isalnum():
        raise StepError("Variable names can only contain letters, digits and underscores")
    return name


class DefineVariable(Plugin):
    id = "builtin.var_define"
    name = "Define variable"
    icon = "variable"
    color = "purple"
    category = "Variables"
    description = "Creates a named variable that later cards can read or change"
    inputs = [
        Input("name", "text", "Name", magic=False, required=True, placeholder="e.g. counter"),
        Input("type", "select", "Type", default="text", options=VAR_TYPES),
        Input("value", "text", "Initial value", magic=True),
    ]
    outputs = [Output("value", "any", "Value", default=True)]

    async def run(self, ctx, p):
        name = check_name(p["name"])
        typ = p["type"] or "text"
        val = coerce(p["value"], typ, name)
        if typ == "number" and val is None:
            val = 0
        ctx.vars[name] = {"type": typ, "value": val}
        return {"value": val}
