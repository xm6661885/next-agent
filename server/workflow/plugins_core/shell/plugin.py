import asyncio
import os

from server.workflow.sdk import Input, Output, Plugin, StepError

MAX_OUT = 200_000


class ShellCard(Plugin):
    id = "builtin.shell"
    name = "Run shell command"
    icon = "terminal"
    color = "green"
    category = "System"
    description = "Runs a command with bash. Global environment variables are set"
    inputs = [
        Input("command", "code", "Command", magic=True, multiline=True, required=True, placeholder="echo hello"),
        Input("cwd", "text", "Working directory", magic=True, placeholder="Leave empty to use default_cwd"),
        Input("stdin", "text", "Standard input", magic=True, multiline=True, advanced=True),
        Input("fail_on_error", "bool", "Fail on non-zero exit code", default=True, advanced=True),
    ]
    outputs = [
        Output("stdout", "text", "Output", default=True),
        Output("stderr", "text", "Error output"),
        Output("exit_code", "number", "Exit code"),
    ]

    async def run(self, ctx, p):
        env = {**os.environ, **{k: v for k, v in ctx.env.items() if v != ""}}
        proc = await asyncio.create_subprocess_exec(
            "bash", "-c", p["command"],
            cwd=ctx.resolve_cwd(p["cwd"]), env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            out, err = await proc.communicate((p["stdin"] or "").encode())
        except asyncio.CancelledError:
            try:
                os.killpg(proc.pid, 9)
            except ProcessLookupError:
                pass
            raise
        stdout = out.decode(errors="replace")[:MAX_OUT]
        stderr = err.decode(errors="replace")[:MAX_OUT]
        if stderr.strip():
            ctx.log(stderr.rstrip())
        if proc.returncode and p["fail_on_error"]:
            raise StepError(f"Exit code {proc.returncode}: {(stderr or stdout).strip()[-500:]}")
        return {"stdout": stdout.rstrip("\n"), "stderr": stderr, "exit_code": proc.returncode}
