import hmac
import json
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..db import loads, now
from ..sdk import StepError
from .runs import get_run

MAX_BODY = 1024 * 1024


class TriggerBody(BaseModel):
    enabled: bool


def router(core, manager, require):
    api = APIRouter(prefix='/api/workflow')
    db = manager.db

    async def workflow(wid):
        row = await db.fetchone("SELECT * FROM workflows WHERE id=?", (wid,))
        if not row:
            raise HTTPException(404, "Workflow not found")
        return row

    async def record(wid):
        await workflow(wid)
        await db.execute("INSERT OR IGNORE INTO triggers(workflow_id,enabled,token,created_at) VALUES(?,0,?,?)",
                         (wid, secrets.token_urlsafe(32), now()))
        return await db.fetchone("SELECT * FROM triggers WHERE workflow_id=?", (wid,))

    def view(row):
        return dict(enabled=bool(row['enabled']), token=row['token'],
                    path=f"/api/workflow/trigger/{row['workflow_id']}", last_used_at=row['last_used_at'])

    @api.get('/workflows/{wid}/trigger', dependencies=[Depends(require)])
    async def get_trigger(wid: str):
        return view(await record(wid))

    @api.patch('/workflows/{wid}/trigger', dependencies=[Depends(require)])
    async def patch_trigger(wid: str, body: TriggerBody):
        await record(wid)
        await db.execute("UPDATE triggers SET enabled=? WHERE workflow_id=?", (body.enabled, wid))
        return view(await db.fetchone("SELECT * FROM triggers WHERE workflow_id=?", (wid,)))

    @api.post('/workflows/{wid}/trigger/regenerate', dependencies=[Depends(require)])
    async def regenerate(wid: str):
        await record(wid)
        await db.execute("UPDATE triggers SET token=? WHERE workflow_id=?", (secrets.token_urlsafe(32), wid))
        return view(await db.fetchone("SELECT * FROM triggers WHERE workflow_id=?", (wid,)))

    @api.post('/trigger/{wid}')
    async def trigger(wid: str, request: Request, wait: bool = False,
                      timeout: float = Query(60, gt=0, le=300, allow_inf_nan=False)):
        row = await workflow(wid)
        config = await db.fetchone("SELECT * FROM triggers WHERE workflow_id=?", (wid,))
        if not config or not config['enabled']:
            raise HTTPException(403, "Trigger disabled")
        scheme, _, bearer = request.headers.get('authorization', '').partition(' ')
        token = bearer if scheme.lower() == 'bearer' else request.headers.get('x-workflow-token', request.query_params.get('token', ''))
        if not hmac.compare_digest(token.encode(), config['token'].encode()):
            raise HTTPException(401, "Invalid workflow token")
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_BODY:
                raise HTTPException(413, "Body exceeds 1 MiB")
            raw.extend(chunk)
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            raise HTTPException(400, "Body must be a JSON object") from None
        if not isinstance(body, dict):
            raise HTTPException(400, "Body must be a JSON object")
        definition = loads(row['definition'])
        names = {spec['name'] for spec in definition.get('inputs', []) if spec.get('name')}
        try:
            run_id = await manager.start_run(definition, workflow_id=wid, workflow_name=row['name'],
                                             inputs={k: v for k, v in body.items() if k in names}, trigger='webhook')
        except StepError as exc:
            raise HTTPException(400, str(exc)) from None
        await db.execute("UPDATE triggers SET last_used_at=? WHERE workflow_id=?", (now(), wid))
        if not wait:
            return JSONResponse({'run_id': run_id, 'status': 'queued'}, status_code=202)
        finished = await manager.wait(run_id, timeout)
        return {**await get_run(run_id, db, full=False), 'run_id': run_id, 'done': finished}

    return api
