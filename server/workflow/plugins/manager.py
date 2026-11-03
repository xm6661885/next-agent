"""Plugin scanning and hot reload.

Each plugin is a folder containing plugin.py. Every load uses a fresh module name and old modules are left to the GC.
A failed load only affects the folder that broke. A running Run took a snapshot at start and keeps using the old classes.
"""
import asyncio
import importlib.util
import inspect
import itertools
import sys
import traceback
from pathlib import Path

from ..sdk import Plugin

_gen = itertools.count(1)


class PluginManager:
    def __init__(self, dirs: list[tuple[Path, str]]):
        self.dirs = dirs  # [(directory, source core|user)]
        self.plugins: dict[str, Plugin] = {}
        self.sources: dict[str, str] = {}
        self.errors: list[dict] = []
        self._watch_task: asyncio.Task | None = None

    # ---- Loading ----
    def load_all(self) -> None:
        gen = next(_gen)
        plugins: dict[str, Plugin] = {}
        sources: dict[str, str] = {}
        errors: list[dict] = []
        for base, source in self.dirs:
            if not base.exists():
                continue
            for folder in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
                entry = folder / "plugin.py"
                if not entry.exists():
                    continue
                try:
                    found = self._load_folder(folder, source, gen)
                    if not found:
                        raise RuntimeError("No Plugin subclass with an id found in plugin.py")
                    for inst in found:
                        if inst.id in plugins:
                            raise RuntimeError(f"Duplicate plugin id: {inst.id}")
                        plugins[inst.id] = inst
                        sources[inst.id] = f"{source}/{folder.name}"
                except BaseException as e:  # noqa: BLE001 - one failing plugin must not take down the others
                    if isinstance(e, (KeyboardInterrupt, SystemExit)):
                        raise
                    missing = isinstance(e, ModuleNotFoundError) and (folder / "requirements.txt").exists()
                    errors.append(
                        {
                            "folder": f"{source}/{folder.name}",
                            "name": folder.name,
                            "error": f"{type(e).__name__}: {e}",
                            "trace": traceback.format_exc(limit=6),
                            "missing_deps": bool(missing),
                        }
                    )
        # clean up old modules
        for name in [n for n in sys.modules if n.startswith("nwplugin_") and not n.startswith(f"nwplugin_{gen}_")]:
            del sys.modules[name]
        self.plugins, self.sources, self.errors = plugins, sources, errors

    def _load_folder(self, folder: Path, source: str, gen: int) -> list[Plugin]:
        modname = f"nwplugin_{gen}_{source}_{folder.name}".replace("-", "_").replace(".", "_")
        spec = importlib.util.spec_from_file_location(
            modname, folder / "plugin.py", submodule_search_locations=[str(folder)]
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[modname] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(modname, None)
            raise
        out = []
        for obj in vars(module).values():
            if inspect.isclass(obj) and issubclass(obj, Plugin) and obj is not Plugin and obj.__module__ == modname:
                if not obj.id:
                    continue
                out.append(obj())
        return out

    # ---- Queries ----
    def snapshot(self) -> dict[str, Plugin]:
        return dict(self.plugins)

    def schemas(self, env_keys: set[str] | None = None) -> list[dict]:
        res = []
        for pid, p in self.plugins.items():
            s = p.schema()
            s["source"] = self.sources.get(pid, "")
            if env_keys is not None:
                s["missing_env"] = [k for k in p.requires_env if k not in env_keys]
            res.append(s)
        return res

    # ---- File watching ----
    def start_watch(self, path: Path) -> None:
        self.stop_watch()
        self._watch_task = asyncio.create_task(self._watch(path))

    def stop_watch(self) -> None:
        if self._watch_task:
            self._watch_task.cancel()
            self._watch_task = None

    @property
    def watching(self) -> bool:
        return self._watch_task is not None and not self._watch_task.done()

    async def _watch(self, path: Path) -> None:
        from watchfiles import awatch

        path.mkdir(parents=True, exist_ok=True)
        async for _ in awatch(path, debounce=800, recursive=True):
            try:
                self.load_all()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
