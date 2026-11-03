from server.workflow.sdk import Input, Output, Plugin


class AskInputCard(Plugin):
    id = "builtin.ask_input"
    name = "Ask for input"
    icon = "help"
    color = "yellow"
    category = "Interaction"
    description = "Pauses the run here and continues after you fill in a value in the UI"
    inputs = [
        Input("prompt", "text", "Prompt", magic=True, multiline=True, default="Enter a value"),
        Input("default", "text", "Default value", magic=True),
        Input("multiline", "bool", "Multiline input", default=False, advanced=True),
    ]
    outputs = [Output("text", "text", "Input value", default=True)]

    async def run(self, ctx, p):
        fields = [{"name": "text", "label": p["prompt"], "type": "text", "default": p["default"], "multiline": p["multiline"]}]
        values = await ctx.request_input(p["prompt"], fields)
        return {"text": str(values.get("text", ""))}
