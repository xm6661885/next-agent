---
name: autotask
description: Create and manage scheduled tasks, fixed-interval tasks, one-off timed tasks, or long-running tasks started immediately in the background (Python/Shell) via the autotask CLI, and view task status and run logs. Use when the user mentions cron, scheduled execution (定时执行, 定时任务), running something daily/hourly (每天/每小时跑一次), running at a specific time (某时间点运行), running a script in the background (后台跑脚本), or registering a script as a scheduled task (把脚本注册成定时任务). For scheduled file sync/backup tasks (文件同步/备份), use filesync.
metadata:
  author: AutoTask
  version: 3.0.0
  tags:
  - autotask
  - cron
  - scheduler
  - one-off
  - cli
---

# autotask — automated script runner

AutoTask is next-agent’s Automations module. Use `autotask` for CLI management; the scheduler runs inside `next-agent.service`, with no separate service or `autotaskd`. Runs use transient systemd user scopes named `autotask-<task>-<run>` (task/run IDs).

Run first:

~~~bash
autotask status
~~~

Trust the actual script directory, data directory, and time zone shown in its output; do not assume the install path.

## Choose the task type first

Before creating, decide whether the task needs to run repeatedly; this determines the script directory, scheduling method, and home page section.

| Type | Use case | Scheduling | Script location |
| --- | --- | --- | --- |
| recurring | Manual, cron, interval, or webhook work that can run repeatedly | manual, cron, interval, webhook | scripts/cron/<task_name>/ |
| one_off | Runs only once at a given time, or a long task sent to the background immediately | Internally once; triggered immediately or at a set time | scripts/once/<task_name>/ |

- Each task has its own directory; the entry script, prompts, state files, and helper modules should all live there.
- A one-off task is atomically claimed from pending once per execution round; completion records completed/failed and stops scheduling. History and logs are kept, and terminal tasks can explicitly run again.
- Existing manual tasks remain recurring tasks and can be run manually many times.
- Task names are globally unique and are also used for CLI references and the task directory; pick a stable, readable name.

## Directory and script conventions

The deployed root is `/home/xm666/next-agent`: scripts are in `data/automations/scripts/{cron,once,lib}`, DB in `data/automations/autotask.db`, logs in `data/automations/logs`, config in `data/config/automations.toml`, and the task Python venv in `data/automations/venv`. Trust `autotask status` for resolved paths/timezone; `NEXT_AGENT_DATA` can override the data root.

~~~text
scripts/
├── cron/
│   └── daily_backup/
│       ├── daily_backup.sh
│       └── state.json
└── once/
    └── export_2026_09/
        ├── export_2026_09.py
        └── input.csv
~~~

- `.py` uses configured `python_bin` (normally the task venv’s `bin/python`); `.sh` uses configured `shell_bin` (normally `/bin/bash`). Other executable files are supported. Dependencies are not installed automatically; the configured Python’s directory is prepended to PATH.
- cwd is the current task directory, not the scripts root. When referencing sibling files, prefer relative paths or derive them from the script's own location; never hardcode old .../scripts/<file> paths.
- In Shell use TASK_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"; in Python use Path(__file__).resolve().parent.
- Do not move the entry script yourself after registration; if you really need to change the entry, first put the new script in the same task directory, then update it with `autotask edit <task> --script cron/<task_name>/<new_file>`.
- Migrated tasks retain their recurring/one-off kind and dedicated directories. Check for hardcoded paths to the former scripts root; shared helpers belong in scripts/lib/, while separate task state stays in each task directory.

## Create a recurring task

create builds the task directory and skeleton by type; it is written to the scheduling database only with --register.

~~~bash
# Run every day at 2 AM
autotask create daily_backup --type shell --description "备份数据库" \
  --register --kind recurring --schedule-type cron --schedule-value "0 2 * * *"

# Run once every hour
autotask create check_disk --type python --description "检查磁盘空间" \
  --register --kind recurring --schedule-type interval --schedule-value 3600

# Can be run manually repeatedly
autotask create repair_cache --type shell --description "修复缓存" \
  --register --kind recurring --schedule-type manual
~~~

- --kind recurring is the default type.
- --schedule-type manual|cron|interval|webhook defaults to manual; manual and webhook do not need --schedule-value.
- --description / -d describes the task's purpose. create also writes it into the skeleton comments, and it is shown in the task list.
- --args is a JSON array of default arguments, e.g. '["--verbose"]'; --name overrides the task name derived from the file name; --disabled registers without enabling.

## Create a one-off task

One-off tasks are for a single scheduled run or long background work. They must be registered at creation; do not simulate one-off runs with a temporary cron.

~~~bash
# Run once at a given time in the host's local time
autotask create monthly_export --type python --description "导出本月数据" \
  --register --kind one-off --once-at "2027-01-21 09:30"

# Start a long task immediately, once; it keeps running in the background after the CLI returns
autotask create archive_media --type shell --description "归档媒体库" \
  --register --kind one-off --run-once
~~~

- --kind one-off creates a one-off task; the script goes into scripts/once/<task_name>/.
- --once-at 'YYYY-MM-DD HH:MM' schedules one run in the host's local time zone; it must be in the future.
- --run-once queues one background run for next-agent’s next scheduler tick; the service must be running. No foreground wait is needed; watch progress via logs or the Web UI.
- Use either --once-at or --run-once, not both; one-off tasks cannot use cron, interval, or webhook.

## Register an existing script

First put the entry script and its dependencies into the target task directory, then use add with the path relative to the scripts root:

~~~bash
# scripts/cron/cleanup/cleanup.sh
autotask add cleanup cron/cleanup/cleanup.sh --kind recurring \
  --description "清理历史日志" --schedule-type cron --schedule-value "0 */6 * * *"

# scripts/once/import_once/import_once.py
autotask add import_once once/import_once/import_once.py --kind one-off \
  --description "导入供应商文件" --once-at "2027-01-22 10:00"

# Run an existing script immediately as a background one-off long task
autotask add reindex_once once/reindex_once/reindex_once.sh --kind one-off \
  --description "重建搜索索引" --run-once
~~~

add --description is task metadata shown in the CLI/web list; it is not the file name. If migrated tasks have empty descriptions, fill them in with `autotask edit <task> -d "description"`.

## Manage and inspect

~~~bash
autotask list
autotask list --json
autotask list --group 未分组
autotask enable <task name or ID>
autotask disable <task name or ID>
autotask cancel <task name or ID>       # Cancel a one-off task that has not started yet
autotask remove <task name or ID>       # Delete the task definition and run records, not the task directory

# Manually run a recurring task
autotask run daily_backup
autotask run daily_backup --wait
autotask run --wait daily_backup -- --target /mnt/backup --compress

# View records or the latest full log
autotask logs daily_backup --count 10
autotask logs archive_media --latest
~~~

- autotask run is normally used to trigger recurring tasks by hand. A one-off task still waiting can also be started early with it, but you cannot append arguments or use --force; if you need it to run in the background immediately at creation, use --run-once.
- By default a task will not start again while it is running; run --force runs concurrently, use it only if the script is reentrant.
- A waiting one-off task can be cancelled with autotask cancel; after it has completed, failed, or been cancelled, `autotask run <task name or ID>` starts a new immediate round. This does not delete history and cannot append arguments or use `--force`.
- Removing any task, including a one-off, deletes its task definition and run records. Script directories, task state files and disk logs remain.

## Modify an existing task

Use edit to modify in place, keeping the task ID, group, and run records; do not use remove + add to change config (run records would be lost). Only the given options change; everything else stays the same.

~~~bash
autotask edit <task name or ID> -d "new description"     # Empty string clears the description
autotask edit <task name or ID> --args '["--verbose"]'   # Replace default arguments (JSON string array)
autotask edit <task name or ID> --clear-args             # Clear default arguments
autotask edit <task name or ID> --schedule-type cron --schedule-value "30 6 * * *"
autotask edit <task name or ID> --schedule-value 1800    # Keep the schedule type, change only the cron/interval value
autotask edit <task name or ID> --schedule-type webhook  # manual/webhook need no schedule value
autotask edit <task name or ID> --script cron/<task_name>/new_entry.py
autotask edit <one-off task> --once-at "2027-02-01 09:00" # Only for waiting one-off tasks
~~~

- Task name and type (recurring/one-off) cannot be changed after creation: the name is the task directory. Use enable/disable for recurring tasks and groups move for grouping.
- Changing the schedule recomputes the next run time from the new settings; validation matches the web editor (cron must be valid, interval must be > 0, script must be inside the task's own directory).
- One-off tasks can only be edited while waiting, and have no cron/interval options.
- Changes are written to the database immediately and take effect at next-agent’s next scheduling round, no service restart needed; a run already in progress is unaffected.

## Task groups

Groups affect only the management view; they do not change the recurring/one-off type, schedule, or script path. New tasks are ungrouped by default. Deleting a group returns its tasks to "未分组" (Ungrouped); tasks and run records are kept.

~~~bash
autotask groups list                 # List groups and task counts per group; supports --json
autotask groups create 工作
autotask groups rename 工作 项目工作   # Group name or ID both work
autotask groups move daily_backup 项目工作  # Task name or ID both work
autotask groups ungroup daily_backup
autotask groups delete 项目工作       # Tasks become ungrouped
autotask list --group 项目工作        # Can also use 未分组 (Ungrouped) / 所有任务 (All tasks)
~~~

## Web UI

Open the **Automations** tab at https://agents.xm728070.dpdns.org/ and use the next-agent login. Recurring and one-off views provide creation, editing, run history/logs, enable/disable, run now, stop, cancel and delete.

Group filters offer "所有任务" (All tasks), "未分组" (Ungrouped), and custom groups alongside the task-kind filter. Use group management to create/rename/delete groups and move tasks.

Install/update the CLI from the next-agent checkout with `install -Dm755 scripts/autotask ~/.local/bin/autotask`; the wrapper uses `/home/xm666/next-agent/.venv/bin/python` and that checkout’s module. It shares next-agent’s config/DB. Check `autotask status` after upgrades and `systemctl status next-agent.service` for scheduler health; CLI status alone does not prove the service is running.

"描述" (Description) is the task description shown in the list. After choosing a one-off task, pick "立即执行" (Run now) or "指定时间" (At a set time); the latter uses local date and time, and a waiting scheduled task can also be run early or cancelled. Completed, failed, or cancelled one-off tasks show "再次执行" (Run again); it creates a new immediate-run round and keeps the old run records. Only after choosing a recurring task are the cron, interval, manual, and webhook schedule options shown; script selection is grouped by scripts/cron/ and scripts/once/.

Webhook tasks accept `POST https://agents.xm728070.dpdns.org/api/automations/webhook/<task>`, without UI login. The shared `webhook_secret` in `data/config/automations.toml` is unchanged: auth precedence is nonempty `X-AutoTask-Webhook-Secret`, then `Authorization: Bearer <secret>`, then `?secret=<secret>`; a wrong higher-priority credential does not fall through. Send a JSON object (maximum 1 MiB); raw body bytes go to script stdin, headers/query are not forwarded. HTTP 202 means accepted, or skipped if already running (payload discarded).

## Scheduling and time zones

- Use standard five-field cron (minute hour day month weekday), interpreted in next-agent’s system local time zone.
- interval is in seconds, based on the stored previous completion time. Cached next-run timing can cause an immediate follow-up after a long job; do not assume a strict delay after every completion.
- once-at is also interpreted in the system local time zone; the actual time is stored as Unix seconds and converted to local time for display.
- The scheduler checks every 2 seconds by default, allowing a few seconds of drift. Once claimed, a one-off task does not enter the next scheduling round.


## Troubleshooting and security

- One-off task did not start: confirm pending state and host-local time, check `systemctl status next-agent.service`, `autotask status`, `autotask logs <task_name> --latest`, and `journalctl -u next-agent -f`.
- Recurring task did not fire on time: check enabled state, cron/interval value, next-run time, service health and system time zone. Inspect `autotask logs <task_name>` and `journalctl -u next-agent`; do not rely on a restart to reset cached times.
- Script cannot find files: check that the task was migrated to the correct directory, and switch to paths relative to the script directory or derived from __file__ / BASH_SOURCE.
- Scripts run as the next-agent service user; task arguments are stored in plaintext in SQLite. Run only trusted scripts and read secrets from protected config or environment variables. Use HTTPS for remote access. Stop running tasks in the UI; there is no public CLI stop command.
