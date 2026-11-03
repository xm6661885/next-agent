"""The ctx passed to a plugin's run()."""
import asyncio
from pathlib import Path
from typing import Any


class StopRun(Exception):
    """Raised by the Stop and output card. Ends the current (sub-)workflow and returns the result."""

    def __init__(self, value: Any = None):
        self.value = value


class Ctx:
    def __init__(self, runner, st, block: dict, path: list[str], depth: int = 0, scope=None):
        self._runner = runner
        self._st = st
        self.block = block
        self.block_id: str = block["id"]
        self.path = "/".join(path)
        self._path_list = path
        self._depth = depth
        self.run_id: str = st.run_id
        self.workflow_name: str = st.workflow_name
        self.env: dict[str, str] = st.env  # global environment variables
        self.bridge = runner.core.bridge
        self.services: dict = runner.services  # replaceable in tests (e.g. a fake claude client)
        self.cancel_event: asyncio.Event = st.cancel_event
        # named variables of the current (sub-)workflow: name -> {"type": ..., "value": ...}
        self.vars: dict[str, dict] = scope.vars if scope is not None else {}

    # ---- Console output ----
    def log(self, text: Any) -> None:
        self._runner.bus.emit(self.run_id, "log", {"text": str(text), "path": self.path}, self.block_id)

    def log_event(self, type: str, data: dict) -> None:
        self._runner.bus.emit(self.run_id, type, {**data, "path": self.path}, self.block_id)

    def stream(self, text: str, kind: str = "text") -> None:
        """Streaming text (agent answer/thinking), merged before being pushed to the frontend."""
        if text:
            self._runner.bus.delta(self.run_id, self.block_id, kind, text, self.path)

    def tool_use(self, name: str, tool_input: Any, tool_id: str = "", parent: str | None = None) -> None:
        """parent: tool_use_id of the Agent/Task call when the call comes from a subagent."""
        preview = str(tool_input)
        self._runner.bus.emit(
            self.run_id,
            "tool_use",
            {"name": name, "input": preview[:4000], "id": tool_id, "parent": parent, "path": self.path},
            self.block_id,
        )

    def tool_result(self, content: Any, is_error: bool = False, tool_id: str = "", parent: str | None = None) -> None:
        self._runner.bus.emit(
            self.run_id,
            "tool_result",
            {"content": str(content)[:4000], "is_error": is_error, "id": tool_id, "parent": parent, "path": self.path},
            self.block_id,
        )

    def agent_text(self, text: str, parent: str | None = None) -> None:
        """A complete assistant text block (intermediate output; not passed downstream)."""
        if text:
            self._runner.bus.emit(self.run_id, "agent_text", {"text": text, "parent": parent, "path": self.path}, self.block_id)

    # ---- State ----
    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def add_cost(self, usd: float | None) -> None:
        if usd:
            self._st.cost += float(usd)

    @property
    def default_cwd(self) -> Path:
        raw = self._runner.config.data.server.default_cwd
        return Path(raw).expanduser().resolve() if raw else self._runner.workspace_dir

    def resolve_cwd(self, raw: str | None) -> str:
        """The card's cwd: empty uses default_cwd, relative paths are relative to default_cwd, and the directory is created if missing."""
        p = Path(raw).expanduser() if raw and raw.strip() else self.default_cwd
        if not p.is_absolute():
            p = self.default_cwd / p
        p.mkdir(parents=True, exist_ok=True)
        return str(p)

    # ---- Control flow ----
    def stop(self, value: Any = None) -> None:
        raise StopRun(value)

    async def request_input(self, prompt: str, fields: list[dict], alert: dict | None = None) -> dict:
        return await self._runner.request_input(self._st, self.block_id, self.path, prompt, fields, alert)

    async def run_workflow(self, workflow_id: str, inputs: dict) -> Any:
        return await self._runner.call_subworkflow(
            self._st, workflow_id, inputs, self.block_id, self._path_list, self._depth
        )
