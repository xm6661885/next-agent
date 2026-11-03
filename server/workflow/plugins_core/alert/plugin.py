from server.workflow.sdk import Input, Output, Plugin


class AlertCard(Plugin):
    id = "builtin.alert"
    name = "Show alert"
    icon = "bell"
    color = "yellow"
    category = "Interaction"
    description = "Pauses the run and shows a card on the run page. Cancel stops the workflow"
    inputs = [
        Input("title", "text", "Title", magic=True, default="Alert"),
        Input("message", "text", "Content", magic=True, multiline=True),
        Input("ok_text", "text", "Button text", magic=True, placeholder="OK"),
        Input("show_cancel", "bool", "Show cancel button", default=False),
    ]
    outputs = [Output("ok", "bool", "Confirmed", default=True)]

    async def run(self, ctx, p):
        alert = {"title": p["title"] or "", "message": p["message"] or "",
                 "ok_text": (p["ok_text"] or "").strip() or "OK", "show_cancel": bool(p["show_cancel"])}
        await ctx.request_input(alert["title"], [], alert=alert)
        return {"ok": True}
