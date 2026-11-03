from pathlib import Path

from server.workflow.sdk import Input, Output, Plugin, StepError


class SaveFileCard(Plugin):
    id = "builtin.save_file"
    name = "Save file"
    icon = "file"
    color = "green"
    category = "System"
    description = "Writes text to a file. Relative paths are relative to default_cwd"
    inputs = [
        Input("path", "text", "File name (with path)", magic=True, required=True, placeholder="out/result.txt"),
        Input("content", "text", "Content", magic=True, multiline=True),
        Input("overwrite", "bool", "Overwrite if the file exists", default=True),
    ]
    outputs = [Output("path", "text", "File path", default=True)]

    async def run(self, ctx, p):
        raw = (p["path"] or "").strip()
        if not raw:
            raise StepError("File name is empty")
        f = Path(raw).expanduser()
        if not f.is_absolute():
            f = ctx.default_cwd / f
        if f.is_dir():
            raise StepError(f"{f} is a directory")
        if f.exists() and not p["overwrite"]:
            raise StepError(f"File already exists: {f}")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(p["content"] or "", encoding="utf-8")
        ctx.log(f"Saved {f}")
        return {"path": str(f)}
