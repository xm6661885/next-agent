from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..db import dumps, loads
from ..engine.runner import TERMINAL, RunOpts


def _run(row: dict, full: bool) -> dict:
    out = {
        "id": row["id"],
        "workflow_id": row["workflow_id"],
        "workflow_name": row["workflow_name"],
        "status": row["status"],
        "inputs": loads(row["inputs"], {}),
        "result": loads(row["result"]),
        "error": row["error"],
        "cost_usd": row["cost_usd"],
        "trigger": row["trigger"],
        "base_run_id": row["base_run_id"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }
    if full:
        out["snapshot"] = loads(row["snapshot"], {})
    return out


async def get_run(run_id: str, db, full: bool = True) -> dict:
    row = await db.fetchone("SELECT * FROM runs WHERE id=?", (run_id,))
    if not row:
        raise HTTPException(404, "Run not found")
    return _run(row, full)


class InputBody(BaseModel):
    values: dict = {}


def router(core, manager, require):
    router = APIRouter(prefix='/api/workflow', dependencies=[Depends(require)])
    @router.get("/runs")
    async def list_runs(request: Request, workflow_id: str | None = None, status: str | None = None, finished: bool = False, limit: int = 50, offset: int = 0):
        where, params = [], []
        if finished:
            where.append("status IN ('success','failed','cancelled')")
        if workflow_id:
            where.append("workflow_id=?")
            params.append(workflow_id)
        if status:
            where.append("status=?")
            params.append(status)
        sql = "SELECT * FROM runs" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        rows = await manager.db.fetchall(sql, (*params, min(limit, 200), offset))
        return [_run(r, False) for r in rows]


    @router.get("/runs/{run_id}")
    async def read_run(run_id: str, request: Request):
        return await get_run(run_id, manager.db)


    @router.delete("/runs/{run_id}")
    async def delete_run(run_id: str, request: Request):
        db = manager.db
        row = await db.fetchone("SELECT status FROM runs WHERE id=?", (run_id,))
        if not row:
            raise HTTPException(404, "Run not found")
        if row["status"] not in TERMINAL:
            raise HTTPException(400, "A running run cannot be deleted. Cancel it first")
        for t in ("run_events", "step_outputs"):
            await db.execute(f"DELETE FROM {t} WHERE run_id=?", (run_id,))
        await db.execute("DELETE FROM runs WHERE id=?", (run_id,))
        await manager.refresh_counts()
        return {"ok": True}


    @router.get("/runs/{run_id}/outputs")
    async def run_outputs(run_id: str, request: Request):
        rows = await manager.db.fetchall(
            "SELECT block_id,path,output FROM step_outputs WHERE run_id=?", (run_id,)
        )
        return [{"block_id": r["block_id"], "path": r["path"], **loads(r["output"], {})} for r in rows]


    @router.get("/runs/{run_id}/events")
    async def run_events(run_id: str, request: Request, after: int = 0):
        """SSE: id is the event sequence number; the browser sends Last-Event-ID when reconnecting."""
        bus = manager.bus
        if not await manager.db.fetchone("SELECT 1 FROM runs WHERE id=?", (run_id,)):
            raise HTTPException(404, "Run not found")
        last = request.headers.get("last-event-id")
        if last and last.isdigit():
            after = int(last)

        async def gen():
            yield "retry: 2000\n\n"
            async for ev in bus.subscribe(run_id, after):
                if ev is None:
                    yield ": ping\n\n"
                    continue
                yield f"id: {ev['seq']}\ndata: {dumps(ev)}\n\n"

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )


    @router.post("/runs/{run_id}/cancel")
    async def cancel_run(run_id: str, request: Request):
        if not manager.cancel(run_id):
            raise HTTPException(400, "This run has already finished")
        return {"ok": True}


    @router.post("/runs/{run_id}/input")
    async def provide_input(run_id: str, body: InputBody, request: Request):
        if not manager.provide_input(run_id, body.values):
            raise HTTPException(400, "This run is not waiting for input")
        return {"ok": True}


    @router.post("/runs/{run_id}/rerun")
    async def rerun(run_id: str, request: Request, from_block: str | None = None):
        """Reruns with the old run's snapshot and inputs; with from_block, reuses the outputs before it."""
        runner = manager
        row = await manager.db.fetchone("SELECT * FROM runs WHERE id=?", (run_id,))
        if not row:
            raise HTTPException(404, "Run not found")
        new_id = await runner.start_run(
            loads(row["snapshot"], {}),
            workflow_id=row["workflow_id"],
            workflow_name=row["workflow_name"] or "",
            inputs=loads(row["inputs"], {}),
            trigger=request.state.workflow_trigger,
            opts=RunOpts(base_run_id=run_id, from_block=from_block),
        )
        return {"run_id": new_id, "status": "queued"}

    return router
