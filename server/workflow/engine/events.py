"""Run event bus: broadcasts in memory to SSE subscribers and writes to the database in batches.

- emit() is synchronous (seq allocation is never interrupted by an await). Call `await open_run()` first.
- text_delta events are merged in memory by (card, type) and emitted every ~150ms. Database writes are batched every ~450ms.
  The live stream and the replay therefore see the same events, so Last-Event-ID resume stays aligned.
"""
import asyncio
import time
from collections import defaultdict
from typing import AsyncIterator

from ..db import Database, dumps, loads

REPLAY_PAGE = 200


class EventBus:
    def __init__(self, db: Database):
        self.db = db
        self._seq: dict[str, int] = {}
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._pending: list[tuple] = []
        self._deltas: dict[str, dict[tuple, str]] = {}
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        for rid in list(self._deltas):
            self._flush_deltas(rid)
        await self.flush_db()

    async def _loop(self) -> None:
        tick = 0
        while True:
            await asyncio.sleep(0.15)
            tick += 1
            for rid in list(self._deltas):
                self._flush_deltas(rid)
            if tick % 3 == 0:
                try:
                    await self.flush_db()
                except Exception:  # noqa: BLE001 - a database write failure must not kill the bus
                    pass

    async def open_run(self, run_id: str) -> None:
        row = await self.db.fetchone("SELECT MAX(seq) AS m FROM run_events WHERE run_id=?", (run_id,))
        self._seq[run_id] = (row or {}).get("m") or 0

    async def close_run(self, run_id: str) -> None:
        self._flush_deltas(run_id)
        await self.flush_db()
        self._seq.pop(run_id, None)

    # ---- Publish ----
    def emit(self, run_id: str, type: str, data: dict | None = None, block_id: str | None = None) -> dict:
        self._flush_deltas(run_id)
        return self._push(run_id, type, block_id, data or {})

    def delta(self, run_id: str, block_id: str, kind: str, text: str, path: str = "") -> None:
        d = self._deltas.setdefault(run_id, {})
        key = (block_id, kind, path)
        d[key] = d.get(key, "") + text

    def _flush_deltas(self, run_id: str) -> None:
        items = self._deltas.pop(run_id, None)
        if not items:
            return
        for (block_id, kind, path), text in items.items():
            self._push(run_id, "text_delta", block_id, {"kind": kind, "text": text, "path": path})

    def _push(self, run_id: str, type: str, block_id: str | None, data: dict) -> dict:
        if run_id not in self._seq:  # late event after close_run: drop rather than crash
            return {}
        seq = self._seq[run_id] + 1
        self._seq[run_id] = seq
        ev = {"run_id": run_id, "seq": seq, "ts": time.time(), "block_id": block_id, "type": type, "data": data}
        self._pending.append((run_id, seq, ev["ts"], block_id, type, dumps(data)))
        for q in self._subs.get(run_id, ()):
            q.put_nowait(ev)
        return ev

    async def flush_db(self) -> None:
        if not self._pending:
            return
        batch, self._pending = self._pending, []
        await self.db.executemany(
            "INSERT OR REPLACE INTO run_events(run_id,seq,ts,block_id,type,data) VALUES(?,?,?,?,?,?)", batch
        )

    # ---- Subscribe ----
    async def subscribe(self, run_id: str, after: int = 0, endless: bool = False) -> AsyncIterator[dict | None]:
        """Replay events with seq>after first, then follow live events; ends after run_finished. Yields None as a heartbeat after 15 seconds idle."""
        q: asyncio.Queue = asyncio.Queue()
        self._subs[run_id].add(q)
        try:
            self._flush_deltas(run_id)
            await self.flush_db()
            # replay in pages so a long run is never loaded into memory at once
            last = after
            while True:
                rows = await self.db.fetchall(
                    "SELECT seq,ts,block_id,type,data FROM run_events WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?",
                    (run_id, last, REPLAY_PAGE),
                )
                for r in rows:
                    ev = {**r, "run_id": run_id, "data": loads(r["data"], {})}
                    last = ev["seq"]
                    yield ev
                    if ev["type"] == "run_finished" and not endless:
                        return
                if len(rows) < REPLAY_PAGE:
                    break
                del rows
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), 15)
                except asyncio.TimeoutError:
                    yield None
                    continue
                if ev["seq"] <= last:
                    continue
                last = ev["seq"]
                yield ev
                if ev["type"] == "run_finished" and not endless:
                    return
        finally:
            subs = self._subs.get(run_id)
            if subs is not None:
                subs.discard(q)
                if not subs:
                    self._subs.pop(run_id, None)
