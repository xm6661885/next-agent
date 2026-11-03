"""Execution engine: run creation, queueing, tree traversal, cancel and rerun."""
import asyncio
import logging
import os
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..db import Database, dumps, loads, new_id, now, release_memory
from ..plugins.containers import CONTAINERS
from ..plugins.manager import PluginManager
from ..sdk import StepError
from .context import Ctx, StopRun
from .events import EventBus
from .expr import evaluate
from .variables import Scope, build_tree, coerce, find_invalid_refs, resolve_params, resolve_value, truthy

log = logging.getLogger(__name__)

NO_VALUE = object()
MAX_ITERATIONS = 1000
MAX_DEPTH = 5
TERMINAL = ("success", "failed", "cancelled")


class Limiter:
    """Concurrency gate with an adjustable limit (global agent concurrency)."""

    def __init__(self, limit: int):
        self.limit = max(1, int(limit))
        self.active = 0
        self._cond = asyncio.Condition()

    @property
    def busy(self) -> bool:
        return self.active >= self.limit

    def set_limit(self, n: int) -> None:
        self.limit = max(1, int(n))
        asyncio.get_running_loop().create_task(self._notify())

    async def _notify(self) -> None:
        async with self._cond:
            self._cond.notify_all()

    async def __aenter__(self):
        async with self._cond:
            await self._cond.wait_for(lambda: self.active < self.limit)
            self.active += 1

    async def __aexit__(self, *exc):
        async with self._cond:
            self.active -= 1
            self._cond.notify_all()


@dataclass
class RunState:
    run_id: str
    workflow_name: str
    workflow_id: str | None
    env: dict
    plugins: dict
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    started: bool = False
    finishing: bool = False
    cost: float = 0.0
    input_future: asyncio.Future | None = None


@dataclass
class RunOpts:
    base_run_id: str | None = None
    from_block: str | None = None  # start from this top-level card; earlier outputs come from base_run
    only_block: str | None = None  # run only this top-level card (single card test)
    stop_after: str | None = None  # stop after this top-level card (run to here)


def prepare_inputs(definition: dict, given: dict | None) -> dict:
    """Fills in defaults and coerces types from the workflow's declared inputs."""
    given = dict(given or {})
    out = dict(given)
    for spec in definition.get("inputs") or []:
        name = spec.get("name")
        if not name:
            continue
        val = given.get(name, spec.get("default"))
        typ = spec.get("type", "text")
        out[name] = coerce(val, typ if typ in ("number", "bool", "json", "list") else "text", name)
    return out


def _preview(fields: dict) -> dict:
    return dict(fields)


class RunManager:
    def __init__(self, db: Database, bus: EventBus, plugins: PluginManager, workspace_dir: Path, config, core):
        self.db = db
        self.bus = bus
        self.plugins = plugins
        self.workspace_dir = workspace_dir
        self.config, self.core = config, core
        self.limiter = Limiter(config.data.server.agent_concurrency)
        self.counts = {"workflows": 0, "runs": 0}
        self.services: dict = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.states: dict[str, RunState] = {}
        self._done: dict[str, asyncio.Event] = {}
        self._applied_env: set[str] = set()

    # ------------------------------------------------------------------ Lifecycle
    async def recover_stale(self) -> None:
        rows = await self.db.fetchall("SELECT id,workflow_id FROM runs WHERE status IN ('queued','running','waiting_input')")
        for r in rows:
            rid = r["id"]
            await self.db.execute(
                "UPDATE runs SET status='failed', error=?, finished_at=? WHERE id=?", ("Server restarted, run interrupted", now(), rid)
            )
            self.emit_state(rid, r["workflow_id"], "failed")
            await self.bus.open_run(rid)
            self.bus.emit(rid, "run_finished", {"status": "failed", "error": "Server restarted, run interrupted", "result": None})
            await self.bus.close_run(rid)

    async def shutdown(self) -> None:
        for rid in list(self.tasks):
            self.cancel(rid)
        await asyncio.gather(*list(self.tasks.values()), return_exceptions=True)

    def emit_state(self, run_id, workflow_id, status):
        self.core.emit(dict(type='run_state', module='workflow', run_id=run_id, workflow_id=workflow_id, status=status))

    async def refresh_counts(self):
        self.counts = await self.db.fetchone(
            "SELECT (SELECT COUNT(*) FROM workflows) AS workflows, (SELECT COUNT(*) FROM runs) AS runs")

    async def workflows_changed(self):
        await self.refresh_counts()
        self.core.emit({'type': 'workflow_changed', 'module': 'workflow'})

    # ------------------------------------------------------------------ Public interface
    async def start_run(
        self,
        definition: dict,
        *,
        workflow_id: str | None,
        workflow_name: str,
        inputs: dict | None,
        trigger: str = "ui",
        opts: RunOpts | None = None,
    ) -> str:
        opts = opts or RunOpts()
        prepared = prepare_inputs(definition, inputs)
        run_id = new_id("r")
        await self.db.execute(
            "INSERT INTO runs(id,workflow_id,workflow_name,snapshot,status,inputs,trigger,base_run_id,created_at) "
            "VALUES(?,?,?,?,'queued',?,?,?,?)",
            (run_id, workflow_id, workflow_name, dumps(definition), dumps(prepared), trigger, opts.base_run_id, now()),
        )
        await self.bus.open_run(run_id)
        self.bus.emit(run_id, "run_queued", {"workflow": workflow_name})
        self.emit_state(run_id, workflow_id, "queued")
        await self.refresh_counts()
        self.states[run_id] = RunState(run_id, workflow_name, workflow_id, dict(self.config.data.env), self.plugins.snapshot())
        self._done[run_id] = asyncio.Event()
        self.tasks[run_id] = asyncio.create_task(self._execute(run_id, workflow_name, definition, prepared, opts))
        return run_id

    def cancel(self, run_id: str) -> bool:
        st = self.states.get(run_id)
        task = self.tasks.get(run_id)
        if not task or st.finishing:
            return False
        if not st.cancel_event.is_set():
            st.cancel_event.set()
            if st.started: task.cancel()
        return True

    def provide_input(self, run_id: str, values: dict) -> bool:
        st = self.states.get(run_id)
        if st and st.input_future and not st.input_future.done():
            st.input_future.set_result(values)
            return True
        return False

    async def wait(self, run_id: str, timeout: float | None = None) -> bool:
        ev = self._done.get(run_id)
        if ev is None:
            return True
        try:
            await asyncio.wait_for(ev.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    # ------------------------------------------------------------------ Run main flow
    async def _execute(self, run_id: str, name: str, definition: dict, inputs: dict, opts: RunOpts) -> None:
        st = self.states[run_id]
        st.started = True
        status, error, result = "success", None, None
        try:
            if st.cancel_event.is_set(): raise asyncio.CancelledError
            for key in self._applied_env - st.env.keys():
                os.environ.pop(key, None)
            os.environ.update({k: v for k, v in st.env.items() if v != ""})
            self._applied_env = set(st.env)
            await self.db.execute("UPDATE runs SET status='running', started_at=? WHERE id=?", (now(), run_id))
            self.emit_state(run_id, st.workflow_id, "running")
            self.bus.emit(run_id, "run_started", {"workflow": name})
            problems = find_invalid_refs(build_tree(definition.get("blocks") or []))
            if problems:
                raise StepError(f"{len(problems)} variable reference(s) are invalid (the referenced card is not above). Fix them in the editor first")
            result = await self._run_workflow(st, definition, inputs, 0, [], opts)
        except asyncio.CancelledError:
            status, error = "cancelled", "Cancelled"
        except StepError as e:
            status, error = "failed", str(e)
        except Exception as e:  # noqa: BLE001
            log.error("run %s crashed\n%s", run_id, traceback.format_exc())
            status, error = "failed", f"{type(e).__name__}: {e}"
        finally:
            await self._finish(st, status, error, result)

    async def _finish(self, st: RunState, status: str, error: str | None, result: Any) -> None:
        run_id = st.run_id
        st.finishing = True
        await self.db.execute(
            "UPDATE runs SET status=?, error=?, result=?, cost_usd=?, finished_at=? WHERE id=?",
            (status, error, dumps(result), st.cost, now(), run_id),
        )
        self.emit_state(run_id, st.workflow_id, status)
        self.bus.emit(run_id, "run_finished", {"status": status, "error": error, "result": result, "cost_usd": st.cost})
        await self.bus.close_run(run_id)
        try:
            await self.prune()
        except Exception:  # noqa: BLE001
            log.warning("prune failed", exc_info=True)
        if len(self.tasks) == 1:
            try:
                await self.db.checkpoint()
            except Exception:  # noqa: BLE001 - busy readers just postpone it
                pass
            release_memory()
        await self.refresh_counts()
        self.states.pop(run_id, None)
        self.tasks.pop(run_id, None)
        ev = self._done.pop(run_id, None)
        if ev:
            ev.set()

    async def prune(self) -> None:
        keep = self.config.data.server.run_retention
        if keep <= 0:
            return
        await self.db.execute(
            "DELETE FROM runs WHERE status IN ('success','failed','cancelled') "
            "AND id NOT IN (SELECT id FROM runs WHERE status IN ('success','failed','cancelled') ORDER BY created_at DESC LIMIT ?)",
            (keep,),
        )
        await self.db.execute("DELETE FROM run_events WHERE run_id NOT IN (SELECT id FROM runs)")
        await self.db.execute("DELETE FROM step_outputs WHERE run_id NOT IN (SELECT id FROM runs)")

    # ------------------------------------------------------------------ Workflow / cards
    async def _run_workflow(
        self, st: RunState, definition: dict, inputs: dict, depth: int, path: list[str], opts: RunOpts | None
    ) -> Any:
        blocks = build_tree(definition.get("blocks") or [])
        scope = Scope(inputs, st.env)
        todo = blocks
        if opts and depth == 0:
            ids = [b["id"] for b in blocks]
            start = 0
            if opts.only_block and opts.only_block in ids:
                start = ids.index(opts.only_block)
                todo = blocks[start : start + 1]
            elif opts.from_block and opts.from_block in ids:
                start = ids.index(opts.from_block)
                todo = blocks[start:]
            if opts.stop_after and opts.stop_after in ids:
                end = ids.index(opts.stop_after)
                todo = [b for b in todo if ids.index(b["id"]) <= end]
            if start and opts.base_run_id:
                await self._preload(st, scope, blocks[:start], opts.base_run_id)
        try:
            val = await self._exec_blocks(st, todo, scope, path, depth)
        except StopRun as s:
            return s.value
        return val

    async def _preload(self, st: RunState, scope: Scope, blocks: list, base_run_id: str) -> None:
        """Reuses upstream outputs from an old run (no extra cost)."""
        for b in blocks:
            row = await self.db.fetchone(
                "SELECT output FROM step_outputs WHERE run_id=? AND block_id=? AND path=''", (base_run_id, b["id"])
            )
            if not row:
                continue
            out = loads(row["output"], None)
            if not out:
                continue
            if isinstance(out.get("vars"), dict):
                scope.vars.clear()
                scope.vars.update(out.pop("vars"))
            scope.outputs[b["id"]] = out
            await self.db.execute(
                "INSERT OR REPLACE INTO step_outputs(run_id,block_id,path,output) VALUES(?,?,?,?)",
                (st.run_id, b["id"], "", row["output"]),
            )
            self.bus.emit(
                st.run_id,
                "step_output",
                {"path": "", "default": out.get("default"), "fields": _preview(out.get("fields") or {}), "cached": True},
                b["id"],
            )

    async def _exec_blocks(self, st: RunState, blocks: list, scope: Scope, path: list[str], depth: int) -> Any:
        last = None
        for b in blocks:
            v = await self._exec_block(st, b, scope, path, depth)
            if v is not NO_VALUE:
                last = v
        return last

    def _label(self, block: dict) -> str:
        t = block["type"]
        if t in CONTAINERS:
            return CONTAINERS[t]["name"]
        p = self.plugins.plugins.get(t)
        return p.name if p else t

    async def _exec_block(self, st: RunState, block: dict, scope: Scope, path: list[str], depth: int) -> Any:
        bid, btype = block["id"], block["type"]
        pstr = "/".join(path)
        label = self._label(block)
        if block.get("disabled"):
            self.bus.emit(st.run_id, "step_skipped", {"path": pstr, "reason": "Disabled"}, bid)
            return NO_VALUE
        self.bus.emit(st.run_id, "step_started", {"path": pstr, "type": btype, "label": label}, bid)
        t0 = time.time()
        try:
            if btype == "core.if":
                out = await self._exec_if(st, block, scope, path, depth)
            elif btype in ("core.repeat", "core.repeat_each"):
                out = await self._exec_repeat(st, block, scope, path, depth)
            else:
                out = await self._exec_plugin(st, block, scope, path, depth)
        except StopRun as s:
            self.bus.emit(
                st.run_id,
                "step_output",
                {"path": pstr, "default": "result", "fields": _preview({"result": s.value}), "stopped": True},
                bid,
            )
            raise
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            if not isinstance(e, StepError):
                log.error("block %s crashed\n%s", bid, traceback.format_exc())
                e = StepError(f"{type(e).__name__}: {e}")
            if not getattr(e, "labelled", False):
                e = StepError(f"{label}: {e}")
                e.labelled = True
            self.bus.emit(st.run_id, "step_failed", {"path": pstr, "error": str(e)}, bid)
            if block.get("continue_on_error"):
                out = {"fields": {"error": str(e)}, "default": "error"}
                scope.outputs[bid] = out
                return str(e)
            raise e
        scope.outputs[bid] = out
        # top-level cards also snapshot named variables so "rerun from here" can restore them
        saved = {**out, "vars": scope.vars} if not path else out
        await self.db.execute(
            "INSERT OR REPLACE INTO step_outputs(run_id,block_id,path,output) VALUES(?,?,?,?)",
            (st.run_id, bid, pstr, dumps(saved)),
        )
        self.bus.emit(
            st.run_id,
            "step_output",
            {"path": pstr, "default": out["default"], "fields": _preview(out["fields"]), "duration": round(time.time() - t0, 2)},
            bid,
        )
        return out["fields"].get(out["default"])

    # ---- Containers ----
    async def _exec_if(self, st, block, scope, path, depth) -> dict:
        cond = truthy(evaluate((block.get("params") or {}).get("expr"), scope))
        key = "then" if cond else "else"
        self.bus.emit(
            st.run_id, "log", {"text": f"Condition is {'true' if cond else 'false'}, running \"{'If true' if cond else 'Otherwise'}\"", "path": "/".join(path)}, block["id"]
        )
        val = await self._exec_blocks(st, block.get(key) or [], scope, path, depth)
        return {"fields": {"result": val, "branch": key}, "default": "result"}

    async def _exec_repeat(self, st, block, scope, path, depth) -> dict:
        params = block.get("params") or {}
        bid = block["id"]
        if block["type"] == "core.repeat":
            raw = resolve_value(params.get("count", 3), scope)
            n = coerce(raw, "number", "Count") or 0
            items = list(range(1, int(n) + 1))
        else:
            items = coerce(resolve_value(params.get("items"), scope), "list", "List")
        if len(items) > MAX_ITERATIONS:
            raise StepError(f"Loop count exceeds the limit of {MAX_ITERATIONS}")
        results = []
        for i, item in enumerate(items):
            self.bus.emit(
                st.run_id, "loop_iteration", {"path": "/".join(path), "index": i + 1, "total": len(items)}, bid
            )
            scope.loops.append({"id": bid, "item": item, "index": i + 1})
            try:
                results.append(await self._exec_blocks(st, block.get("body") or [], scope, path + [f"{bid}.{i}"], depth))
            finally:
                scope.loops.pop()
        return {"fields": {"result": results, "count": len(items)}, "default": "result"}

    # ---- Regular plugins ----
    async def _exec_plugin(self, st: RunState, block: dict, scope: Scope, path: list[str], depth: int) -> dict:
        plugin = st.plugins.get(block["type"])
        if plugin is None:
            raise StepError(f"Plugin \"{block['type']}\" not found. It may have been deleted or failed to load")
        missing = [k for k in plugin.requires_env if not (st.env.get(k) or os.environ.get(k))]
        if missing:
            raise StepError(f"Missing environment variables: {', '.join(missing)} (add them in Settings)")
        params = resolve_params(plugin.inputs, block.get("params") or {}, scope)
        ctx = Ctx(self, st, block, path, depth, scope)
        timeout = float(block.get("timeout_s") or 0) or None
        attempts = 1 + max(0, int(block.get("retries") or 0))

        async def attempt_loop():
            for n in range(attempts):
                try:
                    coro = plugin.run(ctx, params)
                    return await (asyncio.wait_for(coro, timeout) if timeout else coro)
                except asyncio.TimeoutError:
                    err: Exception = StepError(f"Timed out after {timeout:g} seconds")
                except (StopRun, asyncio.CancelledError):
                    raise
                except StepError as e:
                    err = e
                except Exception as e:  # noqa: BLE001
                    log.error("plugin %s crashed\n%s", plugin.id, traceback.format_exc())
                    err = StepError(f"{type(e).__name__}: {e}")
                if n + 1 >= attempts:
                    raise err
                ctx.log(f"Failed: {err}. Attempt {n + 2}/{attempts}...")
                await asyncio.sleep(1)

        if plugin.uses_agent_slot:
            if self.limiter.busy:
                self.bus.emit(st.run_id, "step_queued", {"path": "/".join(path)}, block["id"])
            async with self.limiter:
                self.bus.emit(st.run_id, "step_started", {"path": "/".join(path), "type": block["type"], "label": self._label(block)}, block["id"])
                res = await attempt_loop()
        else:
            res = await attempt_loop()

        default = plugin.default_output()
        fields = res if isinstance(res, dict) else {default: res}
        if default not in fields and fields:
            default = next(iter(fields))
        return {"fields": fields, "default": default}

    # ------------------------------------------------------------------ ctx callbacks
    async def request_input(self, st: RunState, block_id: str, path: str, prompt: str, fields: list[dict], alert: dict | None = None) -> dict:
        fut = asyncio.get_running_loop().create_future()
        st.input_future = fut
        await self.db.execute("UPDATE runs SET status='waiting_input' WHERE id=?", (st.run_id,))
        self.emit_state(st.run_id, st.workflow_id, "waiting_input")
        self.bus.emit(st.run_id, "waiting_input", {"prompt": prompt, "fields": fields, "alert": alert, "path": path}, block_id)
        try:
            values = await fut
            await self.db.execute("UPDATE runs SET status='running' WHERE id=?", (st.run_id,))
            self.emit_state(st.run_id, st.workflow_id, "running")
            self.bus.emit(st.run_id, "input_received", {"path": path}, block_id)
            return values
        finally:
            st.input_future = None

    async def call_subworkflow(
        self, st: RunState, workflow_id: str, inputs: dict, block_id: str, path: list[str], depth: int
    ) -> Any:
        if depth + 1 >= MAX_DEPTH:
            raise StepError("Sub-workflow nesting is too deep")
        row = await self.db.fetchone("SELECT name, definition FROM workflows WHERE id=?", (workflow_id,))
        if not row:
            raise StepError(f"Sub-workflow {workflow_id} not found")
        definition = loads(row["definition"], {})
        if find_invalid_refs(build_tree(definition.get("blocks") or [])):
            raise StepError(f"Sub-workflow \"{row['name']}\" has invalid variable references")
        return await self._run_workflow(
            st, definition, prepare_inputs(definition, inputs), depth + 1, path + [block_id], None
        )
