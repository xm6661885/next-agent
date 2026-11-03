from server.workflow.sdk import Input, Output, Plugin


class TextCard(Plugin):
    id = "builtin.text"
    name = "Text"
    icon = "text"
    color = "gray"
    category = "Text"
    description = "Joins text and can include magic variables"
    inputs = [Input("text", "text", "Text", magic=True, multiline=True)]
    outputs = [Output("text", "text", "Text", default=True)]

    async def run(self, ctx, p):
        return {"text": p["text"]}
