# Automations

AutoTask 2.1.1 task/group/run persistence and CLI are hosted in next-agent. The UI is a separate frontend track.
All management routes below are under **`/api/automations`** and require next-agent authentication (`core.require`,
normal `na_auth` cookie). They accept JSON and return JSON. Missing authentication is 401; missing task/group/run is 404;
conflicting lifecycle state or duplicate task name is 409; invalid inputs, duplicate/invalid group names, and invalid
query bounds are 422 (`{"detail": ...}`). No legacy Flask URLs, session cookies, HTML forms or password settings remain.
The public webhook has its own exact response contract, documented separately below.

## Task representation

Tasks are sorted by ascending ID. API responses contain all database columns and the derived fields below. Timestamps
are Unix seconds (`number|null`), never formatted local strings. The host timezone is returned by settings.

```ts
type Task = {
  id: number; name: string; description: string; script: string;
  args: string;                    // Stored JSON array string, preserved for CLI/DB parity
  args_list: string[];             // API convenience field
  schedule_type: 'manual'|'cron'|'interval'|'webhook'|'once';
  schedule_value: string|null;
  enabled: number;                 // SQLite 0 or 1
  created_at: number; updated_at: number;
  last_run_at: number|null;        // Completion, not start time
  next_run_at: number|null;
  running_pid: number|null; running: boolean;
  task_kind: 'recurring'|'one_off';
  scheduled_at: number|null;
  one_off_trigger: 'immediate'|'scheduled'|null;
  one_off_state: 'pending'|'running'|'completed'|'failed'|'cancelled'|null;
  group_id: number|null; group_name: string|null;
  failure_ack_run_id: number|null;
  last_exit_code: number|null;     // Newest finished run by run ID
  last_finished_run_id: number|null;
  failure_acked: boolean;
}
```

`{ref}` accepts a numeric task ID or an exact task name; all-digit references are IDs, as in the CLI.
Task deletion removes task/run database records but preserves script directories, task-owned state and disk logs.
Name and kind are immutable; a task's scripts must remain inside its dedicated directory.

| Method | Route | Request / response |
|---|---|---|
| GET | `/tasks` | `Task[]`, all tasks; frontend combines kind/group filters |
| GET | `/tasks/status` | Object keyed by string task ID; each value has `running, enabled, last_run_at, next_run_at, last_exit_code, failure_acked, task_kind, one_off_state, one_off_trigger, scheduled_at` using the types above |
| GET | `/tasks/{ref}` | `Task` |
| GET | `/tasks/{ref}/status` | One value from the bulk status map |
| POST | `/tasks` | Create payload below; 201 `Task` |
| PATCH | `/tasks/{ref}` | Edit payload below; 200 `Task` |
| DELETE | `/tasks/{ref}` | 200 `{ok:true}`; rejects a stored running PID |
| POST | `/tasks/{ref}/run` | Optional `{force?:boolean,extra_args?:string[]}` (defaults false/[]); `{run_id:number}` |
| POST | `/tasks/{ref}/start` | No body; start a pending one-off early; `{run_id:number}` |
| POST | `/tasks/{ref}/run-again` | No body; requeue and start a terminal one-off; `{run_id:number}` |
| POST | `/tasks/{ref}/stop` | No body; SIGTERM to the stored process group; `{ok:true}`; not running/failed signal is 409 |
| POST | `/tasks/{ref}/enable` | No body; enable recurring task and recompute next run; `Task` |
| POST | `/tasks/{ref}/disable` | No body; disable recurring task and clear next run; `Task` |
| POST | `/tasks/{ref}/toggle` | No body; invert recurring enabled state; `Task` |
| POST | `/tasks/{ref}/cancel` | No body; atomically cancel pending one-off; `{ok:true}` |

Manual recurring runs ignore `enabled`. Without `force`, a stored running PID prevents a second run. `force` preserves
AutoTask's lossy single-PID overlap semantics: later workers overwrite the PID and any finishing worker clears it.
One-offs reject `force` or extra args. `/run` starts pending one-offs early and requeues terminal ones; `/start` and
`/run-again` additionally restrict the permitted source state. Claim races return 409. Enable/disable/toggle reject
one-offs; use cancel or run-again. Disabling does not stop a running child.

### Create payload

```json
{
  "name": "daily",
  "description": "Daily check",
  "script": "cron/daily/daily.sh",
  "args": [],
  "task_kind": "recurring",
  "schedule_type": "cron",
  "schedule_value": "0 9 * * *",
  "enabled": true
}
```

`name` is required, trimmed, nonempty, cannot equal `.`/`..` or contain `/`, `\`, NUL. Description defaults empty,
is trimmed and limited to 1000 characters. `args` defaults `[]` and must contain strings. `task_kind` defaults
`recurring`; `schedule_type` defaults `manual`. Cron requires a croniter-valid expression; interval requires finite
positive seconds encoded as a string. Manual/webhook values are normalized to null. `enabled` defaults true.
Script must be an existing regular file contained by realpath in `scripts/cron/<name>/` for recurring or
`scripts/once/<name>/` for one-offs. Nested script directories are permitted.

To create a conventional script skeleton instead of selecting an existing script, omit `script` and send
`"create_script":"python"` or `"shell"`. This creates `<name>.py` or `<name>.sh` in the correct task directory,
with the description in its header and executable bits, using the CLI templates. Existing files are never overwritten
by this API; supplying both `script` and `create_script` is invalid.

For one-offs set `task_kind:"one_off"`. `one_off_trigger` defaults `immediate`; for a future time send
`one_off_trigger:"scheduled"` and either numeric `scheduled_at` or ISO `scheduled_at_local` such as
`"2027-01-01T09:00"`. When both time formats are present, local ISO takes precedence. Naive ISO uses the host timezone;
aware ISO is converted to it. Scheduled times must be in the future. One-offs always start as enabled/pending with
`once` schedule and null schedule value. Immediate API create claims/launches immediately; CLI create/add `--run-once`
only queues for the next scheduler tick.

### Edit payload

PATCH accepts only provided `description`, `script`, `args`, `schedule_type`, `schedule_value`, `one_off_trigger`,
`scheduled_at`, `scheduled_at_local`. Empty payload is invalid. Null is accepted only for `schedule_value`.
Name/kind/enabled/group changes are rejected here. `description:""` clears it; `args:[]` clears arguments.
Recurring schedule edits use the current schedule value when the type stays the same; manual/webhook clears it.
Only pending one-offs are editable, with no cron/interval schedule edits. Editing their trigger to immediate launches
them immediately. A schedule/time edit recomputes the next-run cache; description/script/args edits preserve it.
Running recurring tasks may be edited; the already launched worker keeps its captured command and cwd.

## Groups, history, logs and failures

| Method | Route | Request / response |
|---|---|---|
| GET | `/groups` | `[{id:number,name:string,task_count:number}]`, name NOCASE then ID order |
| POST | `/groups` | `{name:string}`; 201 `{id,name,created_at}` |
| PATCH | `/groups/{gid}` | `{name:string}`; `{id,name,created_at}` |
| DELETE | `/groups/{gid}` | `{moved:number}`; members become ungrouped |
| POST | `/groups/{gid}/tasks/{ref}` | No body; move task to group; `{ok:true}` |
| DELETE | `/tasks/{ref}/group` | No body; ungroup task; `{ok:true}` |
| GET | `/tasks/{ref}/runs?limit=50&offset=0` | Run array, newest ID first |
| GET | `/runs?limit=50&offset=0` | Global recent run array, newest ID first |
| GET | `/runs/{run_id}` | One run |
| GET | `/runs/{run_id}/log?offset=0` | `{text:string,offset:number,done:boolean,exit_code:number|null,finished_at:number|null}` |
| GET | `/failures` | `Task[]` of unacknowledged latest failures/abnormal results |
| POST | `/failures/acknowledge` | No body; acknowledge latest finished run of every task; `{ok:true}` |
| GET | `/scripts` | `{recurring:string[],one_off:string[]}` relative script paths |

Group names are trimmed, 1–80 characters, not all digits, not `所有任务` or `未分组`, and unique with SQLite's case-sensitive
comparison. Membership has no execution or filesystem effects. Run pagination has `1 <= limit <= 200`, `offset >= 0`.

```ts
type Run = {
  id:number; task_id:number; started_at:number; finished_at:number|null;
  exit_code:number|null; trigger:string; log_path:string|null;
}
```

Triggers are `manual`, `cron`, `interval`, `webhook`, `once_scheduled`, `once_immediate`. A finished zero exit succeeds;
nonzero fails; a finished null exit is abnormal. Failure list matches the old dashboard: non-running task, nonnull
last completion time, latest exit not zero (including null), and not acknowledged. Acknowledge retains all history/logs.
The separately configured failure-monitor script has its own checkpoint; acknowledgement does not suppress its alerts.

Log read decodes with replacement and returns the next Python file seek/tell offset (not a character count). Offset
must be nonnegative. It reads through current EOF; a missing disk log returns empty text and unchanged offset with DB
completion metadata. Use returned offset for incremental reads. Missing run is 404. `done` means DB completion, not EOF.
There is no truncation, retention, rotation or automatic deletion. Filenames remain `<name>-YYYYMMDD-HHMMSS.log`, including
the old same-second forced-run collision behavior.

The script picker walks cron/once, skips dot-prefixed files/directories, and accepts `.py`, `.sh` or executable regular
files. It includes registered entries and conventional files whose stem equals their immediate containing directory;
unregistered helper scripts are hidden. Realpath validation happens when registering/executing, as before.

## Settings, config and events

| Method | Route | Request / response |
|---|---|---|
| GET | `/settings` | Settings below; secrets are returned in clear |
| PATCH | `/settings` | Partial object of the five TOML keys below; returns settings |
| POST | `/settings/regenerate` | No body; generate/persist a new shared webhook secret; returns settings |

Settings response contains resolved `scripts_dir, python_bin, shell_bin, data_dir`, `poll_interval_sec`, `webhook_secret`,
`config_path`, `timezone`, and `webhook_url` (`https://agents.xm728070.dpdns.org/api/automations/webhook/<task>`).
Config is registered as `automations` with the existing raw config editor (`GET/PUT /api/config/raw?file=automations`)
and appears in `/api/settings/overview`'s files list. The file is `data/config/automations.toml`:

```toml
scripts_dir = "automations/scripts"
python_bin = "automations/venv/bin/python"
shell_bin = "/bin/bash"
webhook_secret = "..."
poll_interval_sec = 2
```

All three relative paths resolve against the data root. `poll_interval_sec` is finite and positive. Removed old keys
`bind_host,port,password_hash,secret_key,data_dir` are not accepted; data is fixed under `data/automations/`.
When creating config, an absent/empty secret is filled from `AUTOTASK_WEBHOOK_SECRET` or a new random token. Migration
copies the existing YAML secret verbatim. An empty secret rejects webhook authentication; reopening the config initializes it as described above.
Config edits update subsequent runs and scheduler polling; active workers keep their snapshots.

Global `/ws/events` emits **`{"type":"automations_changed","module":"automations"}`** after management mutations and
when the one-second database poller sees writes from scheduler/CLI/workers. Clients refresh tasks/groups/history as needed.
The poller uses SQLite data_version so external CLI changes and any run completion are detected, not merely recent rows.

## Public webhook: exact AutoTask contract

`POST /api/automations/webhook/{task_name}` requires no UI cookie. Precedence: a nonempty
`X-AutoTask-Webhook-Secret`, then case-insensitive `Authorization: Bearer <secret>`, then `?secret=`. A wrong higher-priority
credential never falls through. Secrets use constant-time comparison. Content-Type is ignored. Limits apply both to
Content-Length and actual streamed bytes: 1,048,576 bytes maximum, JSON object only. Original bytes are fed to script stdin;
headers/query are not forwarded. The worker deletes the temporary payload file under `data/automations/tmp/`.

Checks occur in this exact order:

| Condition | Status | JSON |
|---|---|---|
| Missing task | 404 | `{success:false,error:"task not found"}` |
| Wrong schedule | 409 | `{success:false,error:"task is not webhook-triggered"}` |
| Disabled | 403 | `{success:false,error:"task is disabled"}` |
| Missing/wrong secret | 401 | `{success:false,error:"invalid webhook secret"}` |
| Body too large | 413 | `{success:false,error:"request body too large"}` |
| Bad JSON | 400 | `{success:false,error:"request body must be valid JSON"}` |
| JSON non-object | 400 | `{success:false,error:"request body must be a JSON object"}` |
| Stored running PID | 202 | `{success:true,skipped:"task is already running",task_name}` |
| Launched | 202 | `{success:true,run_id,task_name}` |

Already-running payloads are discarded, not queued or replayed. A launch error can return 500, as in AutoTask. Other
HTTP methods return 405. The old webhook URL is not aliased; senders must use the new public URL.

## Execution and CLI

The SQLite schema is unchanged (`PRAGMA user_version=5`). Scheduler cron/local-time, interval cache, misfire catch-up,
atomic one-off claim, terminal states and requeue semantics are retained. Cron runs once for overdue cache and recomputes
from now; initial null cache is populated without running on that tick. Running tasks keep overdue caches. Interval cache
is recomputed immediately after launch from the previous completion time, retaining the old immediate-follow-up nuance.

All runs use `python -m server.automations.cli _execute-task ... --run-id ...` in
`sudo -n systemd-run --scope --collect --quiet --unit autotask-<id>-<rid> --uid=<current uid> --gid=<current gid> -- /usr/bin/env KEY=value ... <worker argv>`.
This requires passwordless sudo. The system scope runs as the launching user, with the complete worker environment
passed explicitly after sudo (including HOME, PATH, LANG, task variables, NEXT_AGENT_DATA and PYTHONPATH).
Its cgroup is `/system.slice/autotask-<id>-<rid>.scope`, separate from `next-agent.service`, so workers survive
`systemctl restart next-agent`. No user bus is required. Scope launch failure logs a warning and falls back to detached
Popen, which cannot guarantee restart survival. Stop sends SIGTERM to the script process group under the same UID.
The worker owns stdout/stderr log output, script process group, PID and completion writes. The service only observes DB
state; shutdown leaves workers alone. Recovery tests stored PIDs with `os.kill(pid,0)`: live/permission-denied workers
remain open; dead/unstarted runs get interrupted exit -1 and one-offs fail. A script uses its actual directory as cwd,
Python/shell by extension, otherwise executable directly; no shell interpolation or automatic dependency installation.
Scripts inherit the worker environment, with the configured `python_bin` directory prepended to PATH when that directory
exists. Shell tasks therefore resolve `python`/`python3` from the task environment. LANG/LC_ALL are inherited unchanged.

`python -m server.automations.cli` and the installed `scripts/autotask` wrapper expose the old public commands/flags,
Chinese help and list/groups/log output. CLI accesses DB/files directly and works with the service down. `run --wait`
launches the same worker, prints run ID, waits for DB completion, then prints exit/logs and exits zero only for child zero.
Non-wait recurring run prints `worker_pid`; non-wait one-off retains queue behavior. The old queued message/help still
says `autotaskd`/daemon for output compatibility; next-agent now owns that scheduler. No `autotaskd` executable is provided.
`status` prints new config/scripts/data paths, `服务: next-agent API /api/automations`, timezone and the original totals line.
The internal `_execute-task` help retains its existing visible flags; worker transport flags are hidden. `NEXT_AGENT_DATA`
selects the next-agent data root, including for detached workers; old YAML config discovery is removed.
