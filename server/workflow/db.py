"""Thin aiosqlite wrapper: single connection, WAL, table creation."""
import ctypes
import gc
import json
import secrets
import time
from typing import Any, Iterable

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups(id TEXT PRIMARY KEY, name TEXT NOT NULL, sort INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS workflows(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, group_id TEXT, sort INTEGER NOT NULL DEFAULT 0,
  icon TEXT NOT NULL DEFAULT 'sparkles', color TEXT NOT NULL DEFAULT 'pink',
  definition TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS triggers(
  workflow_id TEXT PRIMARY KEY REFERENCES workflows(id) ON DELETE CASCADE,
  enabled INTEGER NOT NULL, token TEXT NOT NULL, created_at REAL NOT NULL, last_used_at REAL);
CREATE TABLE IF NOT EXISTS runs(
  id TEXT PRIMARY KEY, workflow_id TEXT, workflow_name TEXT, snapshot TEXT NOT NULL,
  status TEXT NOT NULL, inputs TEXT, result TEXT, error TEXT, cost_usd REAL NOT NULL DEFAULT 0,
  trigger TEXT NOT NULL DEFAULT 'ui', base_run_id TEXT,
  created_at REAL NOT NULL, started_at REAL, finished_at REAL);
CREATE INDEX IF NOT EXISTS idx_runs_wf ON runs(workflow_id, created_at DESC);
CREATE TABLE IF NOT EXISTS run_events(
  run_id TEXT NOT NULL, seq INTEGER NOT NULL, ts REAL NOT NULL, block_id TEXT, type TEXT NOT NULL, data TEXT,
  PRIMARY KEY(run_id, seq));
CREATE TABLE IF NOT EXISTS step_outputs(
  run_id TEXT NOT NULL, block_id TEXT NOT NULL, path TEXT NOT NULL DEFAULT '', output TEXT NOT NULL,
  PRIMARY KEY(run_id, block_id, path));
"""

def dumps(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


def loads(s: str | None, default: Any = None) -> Any:
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except ValueError:
        return default


try:
    _malloc_trim = ctypes.CDLL("libc.so.6").malloc_trim
except (OSError, AttributeError):  # not glibc
    _malloc_trim = None


def release_memory() -> None:
    """Collect garbage and return free heap pages to the OS (trades a few ms of CPU for RSS)."""
    gc.collect()
    if _malloc_trim:
        _malloc_trim(0)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(5)}"


def now() -> float:
    return time.time()


class Database:
    def __init__(self, path):
        self.path = str(path)
        self.conn: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA synchronous=NORMAL")
        await self.conn.execute("PRAGMA cache_size=-512")  # 512 KB page cache instead of 2 MB
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def checkpoint(self) -> None:
        """Truncates the WAL file so it does not keep growing (and stay mapped)."""
        await self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()
            self.conn = None

    async def execute(self, sql: str, params: Iterable = ()) -> int:
        cur = await self.conn.execute(sql, tuple(params))
        await self.conn.commit()
        return cur.rowcount

    async def executemany(self, sql: str, rows: list[tuple]) -> None:
        await self.conn.executemany(sql, rows)
        await self.conn.commit()

    async def fetchone(self, sql: str, params: Iterable = ()) -> dict | None:
        async with self.conn.execute(sql, tuple(params)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def fetchall(self, sql: str, params: Iterable = ()) -> list[dict]:
        async with self.conn.execute(sql, tuple(params)) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

