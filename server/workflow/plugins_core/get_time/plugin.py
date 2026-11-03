from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from server.workflow.sdk import Input, Output, Plugin, StepError


class GetTimeCard(Plugin):
    id = "builtin.get_time"
    name = "Get time"
    icon = "clock"
    color = "green"
    category = "Date"
    description = "Gets the current date and time"
    inputs = [
        Input("format", "text", "Format", magic=True, default="%Y-%m-%d %H:%M:%S", description="strftime format"),
        Input("tz", "text", "Time zone", default="Asia/Shanghai", advanced=True, placeholder="e.g. Asia/Shanghai, UTC"),
    ]
    outputs = [
        Output("time", "text", "Time", default=True),
        Output("timestamp", "number", "Timestamp (seconds)"),
        Output("iso", "text", "ISO format"),
    ]

    async def run(self, ctx, p):
        try:
            tz = ZoneInfo(p["tz"] or "UTC")
        except ZoneInfoNotFoundError:
            raise StepError(f"Unknown timezone: {p['tz']}") from None
        now = datetime.now(tz)
        return {"time": now.strftime(p["format"] or "%Y-%m-%d %H:%M:%S"), "timestamp": int(now.timestamp()), "iso": now.isoformat()}
