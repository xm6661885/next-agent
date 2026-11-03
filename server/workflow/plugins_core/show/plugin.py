from server.workflow.sdk import Input, Output, Plugin


class ShowCard(Plugin):
    id = "builtin.show"
    name = "Show result"
    icon = "eye"
    color = "blue"
    category = "Output"
    description = "Writes the content to the run console"
    inputs = [Input("text", "text", "Content", magic=True, multiline=True)]
    outputs = [Output("text", "text", "Content", default=True)]

    async def run(self, ctx, p):
        ctx.log(p["text"])
        return {"text": p["text"]}
