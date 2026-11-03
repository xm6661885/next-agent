import asyncio
import shutil
import sys

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..plugins.containers import CONTAINERS, MARKER_SCHEMAS


class DepsBody(BaseModel):
    folder: str  # e.g. user/my_plugin


def router(core, manager, require):
    router = APIRouter(prefix='/api/workflow/plugins', dependencies=[Depends(require)])
    @router.get("")
    async def list_plugins(request: Request):
        env_keys = {k for k, v in manager.config.data.env.items() if v}
        return {
            "plugins": manager.plugins.schemas(env_keys),
            "containers": list(CONTAINERS.values()),
            "markers": list(MARKER_SCHEMAS.values()),
            "errors": manager.plugins.errors,
            "watching": manager.plugins.watching,
        }


    @router.post("/reload")
    async def reload_plugins(request: Request):
        manager.plugins.load_all()
        return {"count": len(manager.plugins.plugins), "errors": manager.plugins.errors}


    @router.post("/install-deps")
    async def install_deps(body: DepsBody, request: Request):
        """Installs requirements.txt for a user plugin (triggered manually, never auto-run on load)."""
        source, _, name = body.folder.partition("/")
        if source != "user" or not name or "/" in name or name.startswith("."):
            raise HTTPException(400, "Dependencies can only be installed for plugins under data/workflow/plugins")
        req = manager.workspace_dir.parent / "plugins" / name / "requirements.txt"
        if not req.exists():
            raise HTTPException(404, "This plugin has no requirements.txt")
        if shutil.which("uv"):
            cmd = ["uv", "pip", "install", "--python", sys.executable, "-r", str(req)]
        else:
            cmd = [sys.executable, "-m", "pip", "install", "-r", str(req)]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), 300)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise HTTPException(504, "Install timed out") from None
        text = out.decode(errors="replace")[-2000:]
        if proc.returncode != 0:
            raise HTTPException(500, f"Install failed:\n{text}")
        manager.plugins.load_all()
        return {"ok": True, "output": text}

    return router
