from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..engine.variables import flatten, is_nested
from ..db import dumps, loads, new_id, now
from ..engine.runner import RunOpts


EMPTY_DEF = {"inputs": [], "blocks": []}


def _wf(row: dict, full: bool = False) -> dict:
    d = loads(row["definition"], dict(EMPTY_DEF))
    out = {
        "id": row["id"],
        "name": row["name"],
        "group_id": row["group_id"],
        "sort": row["sort"],
        "icon": row["icon"],
        "color": row["color"],
        "updated_at": row["updated_at"],
        "block_count": len(d.get("blocks") or []),
        "inputs": d.get("inputs") or [],
    }
    for k in ("last_status", "last_run_at"):
        if k in row:
            out[k] = row[k]
    if full:
        out["definition"] = d
    return out


# ---------------------------------------------------------------- Groups
class WorkflowCreate(BaseModel):
    name: str = "New workflow"
    group_id: str | None = None
    icon: str = "sparkles"
    color: str = "pink"
    definition: dict | None = None


class WorkflowUpdate(BaseModel):
    name: str | None = None
    group_id: str | None = None
    icon: str | None = None
    color: str | None = None
    sort: int | None = None
    definition: dict | None = None
    clear_group: bool = False


class GroupBody(BaseModel):
    name: str


class ReorderBody(BaseModel):
    ids: list[str]


class RunBody(BaseModel):
    inputs: dict[str, Any] = {}
    wait: bool = False
    timeout: float = 300
    base_run_id: str | None = None
    from_block: str | None = None
    only_block: str | None = None
    stop_after: str | None = None


def router(core, manager, require):
    router = APIRouter(prefix='/api/workflow', dependencies=[Depends(require)])
    @router.get("/groups")
    async def list_groups(request: Request):
        return await manager.db.fetchall("SELECT id,name,sort FROM groups ORDER BY sort, rowid")


    @router.post("/groups")
    async def create_group(body: GroupBody, request: Request):
        db = manager.db
        row = await db.fetchone("SELECT COALESCE(MAX(sort),0)+1 AS n FROM groups")
        gid = new_id("g")
        await db.execute("INSERT INTO groups(id,name,sort) VALUES(?,?,?)", (gid, body.name.strip() or "Untitled group", row["n"]))
        await manager.workflows_changed()
        return {"id": gid, "name": body.name, "sort": row["n"]}


    @router.put("/groups/reorder")
    async def reorder_groups(body: ReorderBody, request: Request):
        db = manager.db
        await db.executemany("UPDATE groups SET sort=? WHERE id=?", [(i, gid) for i, gid in enumerate(body.ids)])
        await manager.workflows_changed()
        return {"ok": True}


    @router.put("/groups/{gid}")
    async def rename_group(gid: str, body: GroupBody, request: Request):
        n = await manager.db.execute("UPDATE groups SET name=? WHERE id=?", (body.name.strip(), gid))
        if not n:
            raise HTTPException(404, "Group not found")
        await manager.workflows_changed()
        return {"ok": True}


    @router.delete("/groups/{gid}")
    async def delete_group(gid: str, request: Request):
        db = manager.db
        await db.execute("UPDATE workflows SET group_id=NULL WHERE group_id=?", (gid,))
        await db.execute("DELETE FROM groups WHERE id=?", (gid,))
        await manager.workflows_changed()
        return {"ok": True}


    # ---------------------------------------------------------------- Workflows
    @router.get("/workflows")
    async def list_workflows(request: Request):
        rows = await manager.db.fetchall(
            "SELECT w.*, "
            "(SELECT status FROM runs r WHERE r.workflow_id=w.id ORDER BY created_at DESC LIMIT 1) AS last_status, "
            "(SELECT created_at FROM runs r WHERE r.workflow_id=w.id ORDER BY created_at DESC LIMIT 1) AS last_run_at "
            "FROM workflows w ORDER BY sort, updated_at DESC"
        )
        return [_wf(r) for r in rows]


    @router.post("/workflows")
    async def create_workflow(body: WorkflowCreate, request: Request):
        db = manager.db
        wid = new_id("wf")
        row = await db.fetchone("SELECT COALESCE(MIN(sort),0)-1 AS n FROM workflows")
        await db.execute(
            "INSERT INTO workflows(id,name,group_id,sort,icon,color,definition,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (wid, body.name, body.group_id, row["n"], body.icon, body.color, dumps(body.definition or EMPTY_DEF), now()),
        )
        await manager.workflows_changed()
        return _wf(await db.fetchone("SELECT * FROM workflows WHERE id=?", (wid,)), full=True)


    @router.put("/workflows/reorder")
    async def reorder_workflows(body: ReorderBody, request: Request):
        await manager.db.executemany(
            "UPDATE workflows SET sort=? WHERE id=?", [(i, wid) for i, wid in enumerate(body.ids)]
        )
        await manager.workflows_changed()
        return {"ok": True}


    @router.post("/workflows/import")
    async def import_workflow(body: dict, request: Request):
        """Imports JSON produced by export: {name, icon, color, definition}."""
        definition = body.get("definition")
        if not isinstance(definition, dict) or not isinstance(definition.get("blocks"), list):
            raise HTTPException(400, "Not a valid workflow file")
        if is_nested(definition["blocks"]):
            definition["blocks"] = flatten(definition["blocks"])
        return await create_workflow(
            WorkflowCreate(
                name=str(body.get("name") or "Imported workflow"),
                icon=body.get("icon") or "sparkles",
                color=body.get("color") or "pink",
                definition=definition,
            ),
            request,
        )


    @router.get("/workflows/{wid}")
    async def get_workflow(wid: str, request: Request):
        row = await manager.db.fetchone("SELECT * FROM workflows WHERE id=?", (wid,))
        if not row:
            raise HTTPException(404, "Workflow not found")
        return _wf(row, full=True)


    @router.put("/workflows/{wid}")
    async def update_workflow(wid: str, body: WorkflowUpdate, request: Request):
        db = manager.db
        row = await db.fetchone("SELECT * FROM workflows WHERE id=?", (wid,))
        if not row:
            raise HTTPException(404, "Workflow not found")
        sets, params = [], []
        for col in ("name", "icon", "color", "sort"):
            v = getattr(body, col)
            if v is not None:
                sets.append(f"{col}=?")
                params.append(v)
        if body.group_id is not None or body.clear_group:
            sets.append("group_id=?")
            params.append(None if body.clear_group else body.group_id)
        if body.definition is not None:
            sets.append("definition=?")
            params.append(dumps(body.definition))
        sets.append("updated_at=?")
        params.append(now())
        await db.execute(f"UPDATE workflows SET {','.join(sets)} WHERE id=?", (*params, wid))
        await manager.workflows_changed()
        return _wf(await db.fetchone("SELECT * FROM workflows WHERE id=?", (wid,)), full=True)


    @router.delete("/workflows/{wid}")
    async def delete_workflow(wid: str, request: Request):
        await manager.db.execute("DELETE FROM workflows WHERE id=?", (wid,))
        await manager.workflows_changed()
        return {"ok": True}


    @router.post("/workflows/{wid}/duplicate")
    async def duplicate_workflow(wid: str, request: Request):
        row = await manager.db.fetchone("SELECT * FROM workflows WHERE id=?", (wid,))
        if not row:
            raise HTTPException(404, "Workflow not found")
        return await create_workflow(
            WorkflowCreate(
                name=row["name"] + " copy",
                group_id=row["group_id"],
                icon=row["icon"],
                color=row["color"],
                definition=loads(row["definition"]),
            ),
            request,
        )


    @router.get("/workflows/{wid}/export")
    async def export_workflow(wid: str, request: Request):
        row = await manager.db.fetchone("SELECT * FROM workflows WHERE id=?", (wid,))
        if not row:
            raise HTTPException(404, "Workflow not found")
        return {
            "format": "next-workflow/1",
            "name": row["name"],
            "icon": row["icon"],
            "color": row["color"],
            "definition": loads(row["definition"]),
        }


    @router.post("/workflows/{wid}/run")
    async def run_workflow(wid: str, body: RunBody, request: Request):
        db, runner = manager.db, manager
        row = await db.fetchone("SELECT * FROM workflows WHERE id=?", (wid,))
        if not row:
            raise HTTPException(404, "Workflow not found")
        trigger = request.state.workflow_trigger
        opts = RunOpts(body.base_run_id, body.from_block, body.only_block, body.stop_after)
        try:
            run_id = await runner.start_run(
                loads(row["definition"]),
                workflow_id=wid,
                workflow_name=row["name"],
                inputs=body.inputs,
                trigger=trigger,
                opts=opts,
            )
        except Exception as e:  # input type coercion failed, etc.
            from ..sdk import StepError

            if isinstance(e, StepError):
                raise HTTPException(400, str(e)) from None
            raise
        if not body.wait:
            return {"run_id": run_id, "status": "queued"}
        finished = await runner.wait(run_id, body.timeout)
        from .runs import get_run

        data = await get_run(run_id, manager.db, full=False)
        data["run_id"] = run_id
        data["done"] = finished
        return data

    return router
