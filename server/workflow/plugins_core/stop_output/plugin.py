from server.workflow.sdk import Input, Plugin


class StopOutputCard(Plugin):
    id = "builtin.stop_output"
    name = "Exit and return"
    icon = "stop"
    color = "red"
    category = "Output"
    description = "Ends the current workflow and uses the content as the run result (this is what an API call returns)"
    inputs = [Input("value", "any", "Return value", magic=True, multiline=True)]
    outputs = []

    async def run(self, ctx, p):
        ctx.stop(p["value"])
