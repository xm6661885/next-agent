import sqlite3
import os
import time
import json
import threading

_lock = threading.Lock()

# Version 2 adds a first-class one-off task lifecycle.  Keeping this separate
# from ``schedule_type`` lets legacy manual/webhook tasks remain repeatable
# while a temporary task can be claimed and completed exactly once.  Version 3
# adds a user-facing task description independent from the script filename.
# Version 4 adds optional groups; task scripts remain in their original paths.
SCHEMA_VERSION = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    script TEXT NOT NULL,
    args TEXT NOT NULL DEFAULT '[]',
    schedule_type TEXT NOT NULL DEFAULT 'manual',  -- manual|cron|interval
    schedule_value TEXT,                            -- cron expr or interval seconds
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_run_at REAL,
    next_run_at REAL,
    running_pid INTEGER,
    task_kind TEXT NOT NULL DEFAULT 'recurring',  -- recurring|one_off
    scheduled_at REAL,                            -- Unix seconds for one_off
    one_off_trigger TEXT,                         -- immediate|scheduled
    one_off_state TEXT                            -- pending|running|completed|failed|cancelled
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    started_at REAL NOT NULL,
    finished_at REAL,
    exit_code INTEGER,
    trigger TEXT NOT NULL DEFAULT 'manual', -- manual|cron|interval|api
    log_path TEXT,
    FOREIGN KEY(task_id) REFERENCES tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_runs_task_id ON runs(task_id);

CREATE TABLE IF NOT EXISTS task_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL
);
"""


class DB:
    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "autotask.db")
        self._init()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init(self):
        with _lock:
            conn = self._connect()
            conn.executescript(SCHEMA)
            self._migrate(conn)
            conn.commit()
            conn.close()

    @staticmethod
    def _migrate(conn):
        """Migrate cached schedule values without changing event timestamps.

        Older releases passed a float Unix timestamp to croniter, which made
        cron wall-clock expressions run as UTC. Existing ``next_run_at``
        values are only a cache, so invalidate them once; the scheduler will
        calculate them using the system timezone on its next tick. Run history
        remains untouched because its Unix timestamps are absolute instants.
        """
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version < 1:
            conn.execute(
                "UPDATE tasks SET next_run_at = NULL WHERE schedule_type = 'cron'"
            )
            version = 1

        if version < 2:
            # SQLite's CREATE TABLE IF NOT EXISTS does not add columns to an
            # existing installation, so keep this migration explicit and
            # idempotent.  All historical tasks are deliberately recurring:
            # a legacy ``manual`` task has always been runnable more than once.
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
            }
            for name, ddl in (
                ("task_kind", "TEXT NOT NULL DEFAULT 'recurring'"),
                ("scheduled_at", "REAL"),
                ("one_off_trigger", "TEXT"),
                ("one_off_state", "TEXT"),
            ):
                if name not in columns:
                    conn.execute(f"ALTER TABLE tasks ADD COLUMN {name} {ddl}")
            conn.execute(
                "UPDATE tasks SET task_kind = 'recurring' "
                "WHERE task_kind IS NULL OR task_kind = ''"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_one_off_due "
                "ON tasks(task_kind, one_off_state, scheduled_at)"
            )
            version = 2

        if version < 3:
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
            }
            if "description" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN description TEXT NOT NULL DEFAULT ''")
            version = 3

        if version < 4:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
            if "group_id" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN group_id INTEGER REFERENCES task_groups(id) ON DELETE SET NULL")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_group_id ON tasks(group_id)")
            version = 4

        if version < 5:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
            if "failure_ack_run_id" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN failure_ack_run_id INTEGER")
            version = 5

        if version < SCHEMA_VERSION:
            raise RuntimeError(f"unsupported AutoTask database migration from v{version}")
        # Kept out of SCHEMA so a v1 database can be opened before its ALTER
        # TABLE migration creates the referenced columns.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_one_off_due "
            "ON tasks(task_kind, one_off_state, scheduled_at)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_group_id ON tasks(group_id)")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    # ---- tasks ----
    @staticmethod
    def _group_name(name):
        name = (name or "").strip()
        if not name or len(name) > 80 or name.isdigit() or name in ("所有任务", "未分组"):
            raise ValueError("分组名称须为 1–80 个字符，不能是纯数字、‘所有任务’或‘未分组’")
        return name

    def list_groups(self):
        with _lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT g.id, g.name, COUNT(t.id) AS task_count "
                "FROM task_groups g LEFT JOIN tasks t ON t.group_id = g.id "
                "GROUP BY g.id ORDER BY g.name COLLATE NOCASE, g.id"
            ).fetchall()
            conn.close()
            return [dict(row) for row in rows]

    def get_group(self, identifier):
        with _lock:
            conn = self._connect()
            if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
                row = conn.execute("SELECT * FROM task_groups WHERE id = ?", (int(identifier),)).fetchone()
            else:
                row = conn.execute("SELECT * FROM task_groups WHERE name = ?", (identifier,)).fetchone()
            conn.close()
            return dict(row) if row else None

    def create_group(self, name):
        name = self._group_name(name)
        with _lock:
            conn = self._connect()
            try:
                cur = conn.execute("INSERT INTO task_groups(name, created_at) VALUES (?, ?)", (name, time.time()))
                conn.commit()
                return cur.lastrowid
            except sqlite3.IntegrityError as e:
                raise ValueError("分组名称已存在") from e
            finally:
                conn.close()

    def rename_group(self, group_id, name):
        name = self._group_name(name)
        with _lock:
            conn = self._connect()
            try:
                cur = conn.execute("UPDATE task_groups SET name = ? WHERE id = ?", (name, group_id))
                conn.commit()
                if not cur.rowcount:
                    raise ValueError("分组不存在")
            except sqlite3.IntegrityError as e:
                raise ValueError("分组名称已存在") from e
            finally:
                conn.close()

    def delete_group(self, group_id):
        with _lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                if not conn.execute("SELECT 1 FROM task_groups WHERE id = ?", (group_id,)).fetchone():
                    raise ValueError("分组不存在")
                moved = conn.execute("UPDATE tasks SET group_id = NULL, updated_at = ? WHERE group_id = ?", (time.time(), group_id)).rowcount
                conn.execute("DELETE FROM task_groups WHERE id = ?", (group_id,))
                conn.commit()
                return moved
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def move_task(self, task_id, group_id):
        with _lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                if group_id is not None and not conn.execute("SELECT 1 FROM task_groups WHERE id = ?", (group_id,)).fetchone():
                    raise ValueError("分组不存在")
                cur = conn.execute("UPDATE tasks SET group_id = ?, updated_at = ? WHERE id = ?", (group_id, time.time(), task_id))
                if not cur.rowcount:
                    raise ValueError("任务不存在")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def create_task(
        self,
        name,
        script,
        args,
        schedule_type,
        schedule_value,
        enabled=True,
        description="",
        task_kind="recurring",
        scheduled_at=None,
        one_off_trigger=None,
        one_off_state=None,
    ):
        now = time.time()
        with _lock:
            conn = self._connect()
            cur = conn.execute(
                "INSERT INTO tasks ("
                "name, description, script, args, schedule_type, schedule_value, enabled, created_at, updated_at, "
                "task_kind, scheduled_at, one_off_trigger, one_off_state"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    name, description or "", script, json.dumps(args), schedule_type, schedule_value,
                    int(enabled), now, now, task_kind, scheduled_at,
                    one_off_trigger, one_off_state,
                ),
            )
            conn.commit()
            task_id = cur.lastrowid
            conn.close()
            return task_id

    def update_task(self, task_id, **fields):
        if not fields:
            return
        fields["updated_at"] = time.time()
        if "args" in fields and not isinstance(fields["args"], str):
            fields["args"] = json.dumps(fields["args"])
        cols = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [task_id]
        with _lock:
            conn = self._connect()
            conn.execute(f"UPDATE tasks SET {cols} WHERE id = ?", vals)
            conn.commit()
            conn.close()

    def claim_one_off(self, task_id, *, allow_early=False):
        """Atomically reserve a pending one-off task for exactly one run.

        The scheduler and a user's "run now" click can race safely: only the
        caller that changes ``pending`` to ``running`` receives the task.  The
        task is disabled at the same time, so a later scheduler tick cannot
        enqueue a second process.
        """
        now = time.time()
        with _lock:
            conn = self._connect()
            due_clause = "" if allow_early else " AND scheduled_at <= ?"
            values = [now, task_id]
            if not allow_early:
                values.append(now)
            cur = conn.execute(
                "UPDATE tasks SET one_off_state = 'running', enabled = 0, "
                "next_run_at = NULL, updated_at = ? "
                "WHERE id = ? AND task_kind = 'one_off' "
                "AND one_off_state = 'pending' AND enabled = 1 "
                "AND running_pid IS NULL" + due_clause,
                values,
            )
            task = None
            if cur.rowcount:
                row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
                task = dict(row) if row else None
            conn.commit()
            conn.close()
            return task

    def cancel_one_off(self, task_id):
        """Cancel a pending one-off without deleting its history."""
        now = time.time()
        with _lock:
            conn = self._connect()
            cur = conn.execute(
                "UPDATE tasks SET one_off_state = 'cancelled', enabled = 0, "
                "next_run_at = NULL, updated_at = ? "
                "WHERE id = ? AND task_kind = 'one_off' "
                "AND one_off_state = 'pending' AND running_pid IS NULL",
                (now, task_id),
            )
            conn.commit()
            conn.close()
            return bool(cur.rowcount)

    def requeue_one_off(self, task_id, *, scheduled_at=None):
        """Make a finished or cancelled one-off eligible for one new run.

        The state transition is intentionally limited to terminal states so a
        second click (or a concurrent scheduler tick) can never duplicate a
        running task.  The caller may then claim it through ``claim_one_off``
        exactly as it would a newly-created task.
        """
        now = time.time()
        scheduled_at = now if scheduled_at is None else scheduled_at
        with _lock:
            conn = self._connect()
            cur = conn.execute(
                "UPDATE tasks SET one_off_state = 'pending', enabled = 1, "
                "scheduled_at = ?, one_off_trigger = 'immediate', "
                "next_run_at = ?, updated_at = ? "
                "WHERE id = ? AND task_kind = 'one_off' "
                "AND one_off_state IN ('completed', 'failed', 'cancelled') "
                "AND running_pid IS NULL",
                (scheduled_at, scheduled_at, now, task_id),
            )
            conn.commit()
            conn.close()
            return bool(cur.rowcount)

    def complete_one_off(self, task_id, exit_code):
        """Persist the terminal state after the single process exits."""
        state = "completed" if exit_code == 0 else "failed"
        with _lock:
            conn = self._connect()
            conn.execute(
                "UPDATE tasks SET one_off_state = ?, enabled = 0, next_run_at = NULL, "
                "updated_at = ? WHERE id = ? AND task_kind = 'one_off' "
                "AND one_off_state = 'running'",
                (state, time.time(), task_id),
            )
            conn.commit()
            conn.close()

    def delete_task(self, task_id):
        with _lock:
            conn = self._connect()
            conn.execute("DELETE FROM runs WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
            conn.close()

    def get_task(self, task_id):
        with _lock:
            conn = self._connect()
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            conn.close()
            return dict(row) if row else None

    def get_task_by_name(self, name):
        with _lock:
            conn = self._connect()
            row = conn.execute("SELECT * FROM tasks WHERE name = ?", (name,)).fetchone()
            conn.close()
            return dict(row) if row else None

    def list_tasks(self):
        with _lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT tasks.*, task_groups.name AS group_name, "
                "(SELECT exit_code FROM runs "
                " WHERE runs.task_id = tasks.id AND runs.finished_at IS NOT NULL "
                " ORDER BY runs.id DESC LIMIT 1) AS last_exit_code, "
                "(SELECT MAX(id) FROM runs "
                " WHERE runs.task_id = tasks.id AND runs.finished_at IS NOT NULL) AS last_finished_run_id "
                "FROM tasks LEFT JOIN task_groups ON task_groups.id = tasks.group_id ORDER BY tasks.id"
            ).fetchall()
            conn.close()
            tasks = [dict(r) for r in rows]
            for t in tasks:
                ack = t.get("failure_ack_run_id")
                t["failure_acked"] = bool(ack and t["last_finished_run_id"] and ack >= t["last_finished_run_id"])
            return tasks

    def clear_failures(self):
        """Acknowledge every task's latest finished run so it no longer counts as a recent failure."""
        with _lock:
            conn = self._connect()
            conn.execute(
                "UPDATE tasks SET failure_ack_run_id = (SELECT MAX(id) FROM runs "
                "WHERE runs.task_id = tasks.id AND runs.finished_at IS NOT NULL)"
            )
            conn.commit()
            conn.close()

    # ---- runs ----
    def create_run(self, task_id, trigger, log_path):
        now = time.time()
        with _lock:
            conn = self._connect()
            cur = conn.execute(
                "INSERT INTO runs (task_id, started_at, trigger, log_path) VALUES (?, ?, ?, ?)",
                (task_id, now, trigger, log_path),
            )
            conn.commit()
            run_id = cur.lastrowid
            conn.close()
            return run_id

    def finish_run(self, run_id, exit_code):
        with _lock:
            conn = self._connect()
            conn.execute(
                "UPDATE runs SET finished_at = ?, exit_code = ? WHERE id = ?",
                (time.time(), exit_code, run_id),
            )
            conn.commit()
            conn.close()

    def recover_interrupted_runs(self):
        """Keep detached live workers; fail abandoned runs and orphaned claims."""
        now = time.time()
        recovered = 0
        with _lock:
            conn = self._connect()
            tasks = conn.execute(
                "SELECT * FROM tasks WHERE id IN (SELECT task_id FROM runs WHERE finished_at IS NULL) "
                "OR (task_kind = 'one_off' AND one_off_state = 'running')"
            ).fetchall()
            for task in tasks:
                if task['running_pid']:
                    try:
                        os.kill(task['running_pid'], 0)
                    except ProcessLookupError:
                        pass
                    except PermissionError:
                        continue
                    else:
                        continue
                conn.execute("UPDATE runs SET finished_at = ?, exit_code = -1 "
                             "WHERE task_id = ? AND finished_at IS NULL", (now, task['id']))
                conn.execute("UPDATE tasks SET running_pid = NULL, last_run_at = ?, updated_at = ?, "
                             "one_off_state = CASE WHEN task_kind = 'one_off' THEN 'failed' ELSE one_off_state END, "
                             "enabled = CASE WHEN task_kind = 'one_off' THEN 0 ELSE enabled END, "
                             "next_run_at = CASE WHEN task_kind = 'one_off' THEN NULL ELSE next_run_at END "
                             "WHERE id = ?", (now, now, task['id']))
                recovered += 1
            conn.commit()
            conn.close()
        return recovered

    def get_open_run(self, task_id):
        with _lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT * FROM runs WHERE task_id = ? AND finished_at IS NULL ORDER BY id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            conn.close()
            return dict(row) if row else None

    def list_runs(self, task_id=None, limit=50, offset=0):
        with _lock:
            conn = self._connect()
            if task_id is not None:
                rows = conn.execute(
                    "SELECT * FROM runs WHERE task_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                    (task_id, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM runs ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
                ).fetchall()
            conn.close()
            return [dict(r) for r in rows]

    def get_run(self, run_id):
        with _lock:
            conn = self._connect()
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            conn.close()
            return dict(row) if row else None
