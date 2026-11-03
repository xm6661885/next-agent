from server.workflow.sdk import Input, Output, Plugin


class SplitTextCard(Plugin):
    id = "builtin.split_text"
    name = "Split text"
    icon = "split"
    color = "gray"
    category = "Text"
    description = "Splits text into a list by a separator. Works well with Repeat for each"
    inputs = [
        Input("text", "text", "Text", magic=True, multiline=True),
        Input("sep", "text", "Separator", default="\\n", description="\\n means a newline"),
        Input("strip", "bool", "Trim whitespace and ignore empty items", default=True, advanced=True),
    ]
    outputs = [Output("list", "list", "List", default=True), Output("count", "number", "Count")]

    async def run(self, ctx, p):
        sep = (p["sep"] or "\\n").replace("\\n", "\n").replace("\\t", "\t")
        parts = p["text"].split(sep)
        if p["strip"]:
            parts = [x.strip() for x in parts if x.strip()]
        return {"list": parts, "count": len(parts)}
