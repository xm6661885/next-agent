"""Built-in container cards of the engine (branch, loops). They do not use the plugin protocol; the schema is declared here for the frontend to render."""
from ..sdk import Input, Output


def _schema(id, name, icon, inputs, outputs, branches, description, markers=()):
    return {
        "id": id,
        "name": name,
        "icon": icon,
        "color": "orange",
        "category": "Control flow",
        "version": "1.0.0",
        "description": description,
        "inputs": [i.to_dict() for i in inputs],
        "outputs": [o.to_dict() for o in outputs],
        "default_output": next(o.name for o in outputs if o.default),
        "requires_env": [],
        "container": True,
        "branches": branches,  # [{"key": "then", "label": "If true"}, ...]
        "markers": markers,  # marker cards inserted together with this one
        "uses_agent_slot": False,
    }


CONTAINERS = {
    "core.if": _schema(
        "core.if",
        "If",
        "branch",
        [
            Input(
                "expr",
                "expr",
                "Condition expression",
                magic=True,
                required=True,
                placeholder='e.g. len(v1) > 100 and "done" in v1',
                description="Python-style expression. Inserted variables map to v1, v2... in order. Text results of true, false or empty are treated as booleans.",
            )
        ],
        [Output("result", "any", "Branch output", default=True), Output("branch", "text", "Branch taken")],
        [{"key": "then", "label": "If true"}, {"key": "else", "label": "Otherwise"}],
        "Chooses which branch to run based on an expression",
        ["core.else", "core.end_if"],
    ),
    "core.repeat": _schema(
        "core.repeat",
        "Repeat",
        "repeat",
        [Input("count", "number", "Count", magic=True, default=3, required=True)],
        [Output("result", "list", "Output per round", default=True), Output("count", "number", "Actual count")],
        [{"key": "body", "label": "Repeat"}],
        "Runs the cards inside several times. Repeat Index is available inside",
        ["core.end_repeat"],
    ),
    "core.repeat_each": _schema(
        "core.repeat_each",
        "Repeat for each",
        "repeat",
        [
            Input(
                "items",
                "list",
                "List",
                magic=True,
                required=True,
                description="JSON array, or text with one item per line",
            )
        ],
        [Output("result", "list", "Output per round", default=True), Output("count", "number", "Actual count")],
        [{"key": "body", "label": "Repeat"}],
        "Runs the cards inside once for each item in the list. Repeat Item and Repeat Index are available inside",
        ["core.end_repeat"],
    ),
}


def _marker(id, name, icon, description):
    return {**_schema(id, name, icon, [], [Output("result", "any", "Result", default=True)], [], description),
            "outputs": [], "default_output": None, "marker": True, "container": False}


# Marker cards close or split a control-flow card; they are added/removed together with it.
MARKER_SCHEMAS = {
    "core.else": _marker("core.else", "Otherwise", "branch", "Cards below run when the condition is false"),
    "core.end_if": _marker("core.end_if", "End If", "branch", "Closes the If card"),
    "core.end_repeat": _marker("core.end_repeat", "End Repeat", "repeat", "Closes the Repeat card"),
}
