import asyncio
import os
from pathlib import Path

from server.workflow.sdk import Input, Output, Plugin, StepError


class NotifyCard(Plugin):
    id = "extra.notify"
    name = "Send notification"
    icon = "bell"
    color = "pink"
    category = "Notify"
    description = "Sends text and an optional attachment with notify"
    inputs = [
        Input("text", "text", "Text", multiline=True, required=True),
        Input("title", "text", "Title"),
        Input("markdown", "bool", "Markdown", default=False),
        Input("attachment", "select", "Attachment", default="none", options=["none", "image", "file"]),
        Input("path", "text", "Attachment path", description="Required for attachments; relative to default_cwd"),
        Input("topic", "text", "Topic", advanced=True),
    ]
    outputs = [Output("ok", "bool", "Accepted", default=True), Output("output", "text", "Command output")]

    async def run(self, ctx, p):
        text = f'{p["title"]}\n{p["text"]}' if p["title"] else p["text"]
        if p["topic"]:
            text = text.rstrip("\n") + f' #{p["topic"]}'
        args = ["notify", "-"]
        if p["markdown"]:
            args.append("--markdown")
        attachment = p["attachment"]
        if attachment != "none":
            if attachment not in ("image", "file"):
                raise StepError("Attachment must be none, image or file")
            if not p["path"] or not p["path"].strip():
                raise StepError("Attachment path is required")
            path = Path(p["path"]).expanduser()
            if not path.is_absolute():
                path = ctx.default_cwd / path
            if not path.is_file():
                raise StepError(f"Attachment is not a file: {path}")
            limit = 10 if attachment == "image" else 50
            if path.stat().st_size > limit * 1024 * 1024:
                raise StepError(f"Attachment exceeds {limit} MiB: {path}")
            args.extend([f"--{attachment}", str(path)])
        proc = await asyncio.create_subprocess_exec(
            *args, env={**os.environ, **ctx.env},
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(text.encode()), 150)
        except asyncio.TimeoutError:
            raise StepError("Notify timed out after 150 seconds") from None
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
        output = out.decode(errors="replace")
        if proc.returncode:
            raise StepError(output + err.decode(errors="replace"))
        return {"ok": True, "output": output}
