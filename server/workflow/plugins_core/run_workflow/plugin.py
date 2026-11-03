from server.workflow.sdk import Input, Output, Plugin


class RunWorkflowCard(Plugin):
    id = "builtin.run_workflow"
    name = "Run workflow"
    icon = "workflow"
    color = "purple"
    category = "Control flow"
    description = "Runs another workflow and returns its output"
    inputs = [
        Input("workflow", "workflow", "Workflow", required=True),
        Input("inputs", "json", "Input parameters", magic=True, multiline=True, description='JSON object, e.g. {"topic": "AI"}'),
    ]
    outputs = [Output("result", "any", "Output", default=True)]

    async def run(self, ctx, p):
        value = await ctx.run_workflow(p["workflow"], p["inputs"] or {})
        return {"result": value}
