import argparse
import datetime as datetime
import json
import os
import stat
import sys
import time

from .db import DB
from .runner import ScriptError, resolve_script
from .scheduler import Scheduler, compute_next_run
from .timezone import system_timezone, system_timezone_name

PY_TEMPLATE = '''#!/usr/bin/env python3
"""{desc}"""
import sys


def main():
    print("hello from {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

SH_TEMPLATE = '''#!/usr/bin/env bash
# {desc}
set -euo pipefail

echo "hello from {name}"
'''


def _normalise_task_kind(value):
    """Return the DB spelling for a CLI/UI task kind."""
    if value in (None, "", "recurring"):
        return "recurring"
    if value in ("one-off", "one_off"):
        return "one_off"
    raise ValueError("任务类型只能是 recurring 或 one-off")


def _task_folder_name(name):
    """Turn a task name into its required, safe per-task directory name."""
    name = (name or "").strip()
    if (
        not name
        or name in (".", "..")
        or "/" in name
        or "\\" in name
        or "\x00" in name
    ):
        raise ValueError("任务名称不能为空，且不能含有路径分隔符")
    return name


def _script_root_for_kind(task_kind):
    return "once" if task_kind == "one_off" else "cron"


def _expected_script_dir(scripts_dir, task_kind, task_name):
    return os.path.realpath(os.path.join(
        scripts_dir, _script_root_for_kind(task_kind), _task_folder_name(task_name)
    ))


def _validate_script_layout(scripts_dir, script, task_kind, task_name):
    """Require every newly registered task to own its script directory."""
    script_path = resolve_script(scripts_dir, script)
    expected_dir = _expected_script_dir(scripts_dir, task_kind, task_name)
    try:
        inside = os.path.commonpath([expected_dir, script_path]) == expected_dir
    except ValueError:
        inside = False
    if not inside:
        root = _script_root_for_kind(task_kind)
        raise ScriptError(
            f"{('一次性' if task_kind == 'one_off' else '重复')}任务的脚本必须放在 "
            f"scripts/{root}/{_task_folder_name(task_name)}/ 下（当前: {script}）"
        )
    return script_path


def _parse_args(raw):
    try:
        parsed = json.loads(raw) if raw else []
    except json.JSONDecodeError as e:
        raise ValueError(f"参数必须是 JSON 数组: {e.msg}") from e
    if not isinstance(parsed, list):
        raise ValueError("参数必须是 JSON 数组，例如 [\"--foo\", \"bar\"]")
    if not all(isinstance(item, str) for item in parsed):
        raise ValueError("参数 JSON 数组中的每一项都必须是字符串")
    return parsed


def _parse_one_off_time(raw):
    """Parse a local ISO-ish time for a one-off task into Unix seconds."""
    try:
        value = datetime.datetime.fromisoformat(raw.strip())
    except (TypeError, ValueError) as e:
        raise ValueError(
            "一次性定时时间格式应为 YYYY-MM-DD HH:MM，例如 2026-09-20 18:30"
        ) from e
    if value.tzinfo is None:
        value = value.replace(tzinfo=system_timezone())
    else:
        value = value.astimezone(system_timezone())
    timestamp = value.timestamp()
    if timestamp <= time.time():
        raise ValueError("一次性定时时间必须晚于当前时间；要马上执行请用 --run-once")
    return timestamp


def _task_options_from_args(args):
    """Validate scheduling flags and produce DB values for a new task."""
    requested_kind = _normalise_task_kind(args.kind)
    wants_one_off = bool(args.once_at or args.run_once)
    if args.once_at and args.run_once:
        raise ValueError("--once-at 和 --run-once 只能选一个")
    if wants_one_off and args.kind == "recurring":
        raise ValueError("一次性选项不能与 --kind recurring 一起使用")

    task_kind = "one_off" if wants_one_off else requested_kind
    if task_kind == "one_off":
        if not wants_one_off:
            raise ValueError("一次性任务请指定 --once-at 或 --run-once")
        if args.disabled:
            raise ValueError("一次性任务不能用 --disabled；可创建后在网页中取消")
        scheduled_at = _parse_one_off_time(args.once_at) if args.once_at else time.time()
        return {
            "task_kind": "one_off",
            "schedule_type": "once",
            "schedule_value": None,
            "scheduled_at": scheduled_at,
            "one_off_trigger": "scheduled" if args.once_at else "immediate",
            "one_off_state": "pending",
            "enabled": True,
        }

    schedule_type = args.schedule_type
    if schedule_type in ("cron", "interval") and not args.schedule_value:
        raise ValueError(f"{schedule_type} 任务需要 --schedule-value")
    return {
        "task_kind": "recurring",
        "schedule_type": schedule_type,
        "schedule_value": None if schedule_type == "webhook" else args.schedule_value,
        "scheduled_at": None,
        "one_off_trigger": None,
        "one_off_state": None,
        "enabled": not args.disabled,
    }


def _create_registered_task(cfg, db, *, name, description, script, task_args, options):
    task_id = db.create_task(
        name=name,
        description=description,
        script=script,
        args=task_args,
        schedule_type=options["schedule_type"],
        schedule_value=options["schedule_value"],
        enabled=options["enabled"],
        task_kind=options["task_kind"],
        scheduled_at=options["scheduled_at"],
        one_off_trigger=options["one_off_trigger"],
        one_off_state=options["one_off_state"],
    )
    task = db.get_task(task_id)
    next_run = compute_next_run(task) if options["enabled"] else None
    db.update_task(task_id, next_run_at=next_run)
    return task_id


def _load(cli_side=True):
    from .config import load_config
    cfg, cfg_path = load_config()
    return cfg, cfg_path, DB(cfg['data_dir'])


def cmd_create(args):
    cfg, cfg_path, db = _load()
    scripts_dir = cfg["scripts_dir"]
    try:
        options = _task_options_from_args(args)
        if options["task_kind"] == "one_off" and not args.register:
            raise ValueError("一次性任务必须使用 --register 创建任务记录")
        # A new file is always rooted in the future task's own directory,
        # whether it is registered in this invocation or later.
        raw_filename = args.filename.strip()
        if os.path.basename(raw_filename) != raw_filename:
            raise ValueError("新脚本文件名不能包含路径；目录会按任务名称自动创建")
        task_name = args.name or os.path.splitext(raw_filename)[0]
        task_name = _task_folder_name(task_name)
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1

    ext = ".py" if args.type == "python" else ".sh"
    filename = raw_filename
    if not filename.endswith(ext):
        filename += ext
    folder = _expected_script_dir(scripts_dir, options["task_kind"], task_name)
    dest = os.path.join(folder, filename)
    if os.path.exists(dest) and not args.force:
        print(f"错误: 文件已存在: {dest} (使用 --force 覆盖)", file=sys.stderr)
        return 1

    desc = args.description or filename
    tmpl = PY_TEMPLATE if args.type == "python" else SH_TEMPLATE
    content = tmpl.format(desc=desc, name=filename)
    os.makedirs(folder, exist_ok=True)
    with open(dest, "w") as f:
        f.write(content)
    st = os.stat(dest)
    os.chmod(dest, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f"已创建脚本: {dest}")

    if args.register:
        if db.get_task_by_name(task_name):
            print(f"提示: 任务名 '{task_name}' 已存在，跳过注册", file=sys.stderr)
            return 0
        try:
            task_args = _parse_args(args.args)
            rel_script = os.path.relpath(dest, scripts_dir)
            task_id = _create_registered_task(
                cfg,
                db,
                name=task_name,
                description=args.description or "",
                script=rel_script,
                task_args=task_args,
                options=options,
            )
        except ValueError as e:
            print(f"错误: {e}", file=sys.stderr)
            return 1
        print(f"已注册任务: {task_name} (id={task_id})")
        if options["task_kind"] == "one_off":
            if options["one_off_trigger"] == "immediate":
                print("一次性任务已入队，将由 autotaskd 立即在后台执行")
            else:
                when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(options["scheduled_at"]))
                print(f"一次性任务已安排在 {when} 执行")
    return 0


def cmd_list(args):
    cfg, cfg_path, db = _load()
    tasks = db.list_tasks()
    if args.group is not None:
        if args.group == "未分组":
            tasks = [t for t in tasks if t["group_id"] is None]
        elif args.group != "所有任务":
            group = db.get_group(args.group)
            if not group:
                print(f"错误: 未找到分组: {args.group}", file=sys.stderr)
                return 1
            tasks = [t for t in tasks if t["group_id"] == group["id"]]
    if args.json:
        print(json.dumps(tasks, ensure_ascii=False, indent=2))
        return 0
    if not tasks:
        print("暂无任务")
        return 0
    for t in tasks:
        if t.get("task_kind", "recurring") == "one_off":
            state_names = {
                "pending": "等待中",
                "running": "运行中",
                "completed": "已完成",
                "failed": "失败",
                "cancelled": "已取消",
            }
            status = state_names.get(t.get("one_off_state"), "未知")
            if t.get("one_off_trigger") == "immediate":
                sched = "一次性：立即执行"
            else:
                sched = "一次性：" + (
                    time.strftime("%Y-%m-%d %H:%M", time.localtime(t["scheduled_at"]))
                    if t.get("scheduled_at") else "时间无效"
                )
        else:
            status = "运行中" if t["running_pid"] else ("启用" if t["enabled"] else "停用")
            sched = t["schedule_type"]
            if sched == "cron":
                sched = f"cron:{t['schedule_value']}"
            elif sched == "interval":
                sched = f"每{t['schedule_value']}秒"
        desc = f" — {t['description']}" if t.get("description") else ""
        group_label = t.get("group_name") or "未分组"
        print(f"[{t['id']:>3}] {t['name']:<20} {t['script']:<42} {sched:<24} {status} [{group_label}]{desc}")
    return 0


def cmd_groups(args):
    cfg, cfg_path, db = _load()
    try:
        if args.group_command == "list":
            groups = db.list_groups()
            if args.json:
                print(json.dumps(groups, ensure_ascii=False, indent=2))
            else:
                for group in groups:
                    print(f"[{group['id']:>3}] {group['name']} ({group['task_count']} 个任务)")
                if not groups:
                    print("暂无分组")
        elif args.group_command == "create":
            group_id = db.create_group(args.name)
            print(f"已创建分组: {args.name.strip()} (id={group_id})")
        elif args.group_command == "rename":
            group = db.get_group(args.group)
            if not group:
                raise ValueError(f"未找到分组: {args.group}")
            db.rename_group(group["id"], args.name)
            print(f"已重命名分组: {group['name']} → {args.name.strip()}")
        elif args.group_command == "delete":
            group = db.get_group(args.group)
            if not group:
                raise ValueError(f"未找到分组: {args.group}")
            moved = db.delete_group(group["id"])
            print(f"已删除分组: {group['name']}，{moved} 个任务移至未分组")
        elif args.group_command in ("move", "ungroup"):
            task = db.get_task(int(args.task)) if args.task.isdigit() else db.get_task_by_name(args.task)
            if not task:
                raise ValueError(f"未找到任务: {args.task}")
            group = None if args.group_command == "ungroup" else db.get_group(args.group)
            if args.group_command == "move" and not group:
                raise ValueError(f"未找到分组: {args.group}")
            db.move_task(task["id"], group["id"] if group else None)
            print(f"任务 {task['name']} 已移至 {group['name'] if group else '未分组'}")
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_add(args):
    cfg, cfg_path, db = _load()
    try:
        options = _task_options_from_args(args)
        _task_folder_name(args.name)
        _validate_script_layout(cfg["scripts_dir"], args.script, options["task_kind"], args.name)
        task_args = _parse_args(args.args)
    except (ScriptError, ValueError) as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    if db.get_task_by_name(args.name):
        print(f"错误: 任务名已存在: {args.name}", file=sys.stderr)
        return 1
    task_id = _create_registered_task(
        cfg,
        db,
        name=args.name,
        description=args.description or "",
        script=args.script,
        task_args=task_args,
        options=options,
    )
    print(f"已添加任务: {args.name} (id={task_id})")
    if options["task_kind"] == "one_off":
        if options["one_off_trigger"] == "immediate":
            print("一次性任务已入队，将由 autotaskd 立即在后台执行")
        else:
            when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(options["scheduled_at"]))
            print(f"一次性任务已安排在 {when} 执行")
    return 0


def cmd_edit(args):
    """Change an existing task's description, script, args or schedule in place.

    Name and kind are fixed (the name is the task directory); enabled state is
    handled by enable/disable.  Run history is kept, unlike remove + add.
    """
    cfg, cfg_path, db = _load()
    task = db.get_task_by_name(args.name) if not args.name.isdigit() else db.get_task(int(args.name))
    if not task:
        print(f"错误: 未找到任务: {args.name}", file=sys.stderr)
        return 1
    kind = task.get("task_kind", "recurring")
    fields = {}
    try:
        if args.args is not None and args.clear_args:
            raise ValueError("--args 和 --clear-args 只能选一个")
        if kind == "one_off":
            if task.get("one_off_state") != "pending":
                raise ValueError("一次性任务只能在等待执行时编辑")
            if args.schedule_type or args.schedule_value:
                raise ValueError("一次性任务没有 cron/间隔调度；改执行时间请用 --once-at")
        elif args.once_at:
            raise ValueError("--once-at 只适用于一次性任务")

        if args.description is not None:
            description = args.description.strip()
            if len(description) > 1000:
                raise ValueError("任务说明不能超过 1000 个字符")
            fields["description"] = description
        if args.script is not None:
            script = args.script.strip()
            _validate_script_layout(cfg["scripts_dir"], script, kind, task["name"])
            fields["script"] = script
        if args.clear_args:
            fields["args"] = []
        elif args.args is not None:
            fields["args"] = _parse_args(args.args)

        if args.once_at:
            fields.update(scheduled_at=_parse_one_off_time(args.once_at), one_off_trigger="scheduled")
        if kind == "recurring" and (args.schedule_type or args.schedule_value):
            schedule_type = args.schedule_type or task["schedule_type"]
            schedule_value = args.schedule_value
            if schedule_value is None and schedule_type == task["schedule_type"]:
                schedule_value = task["schedule_value"]
            if schedule_type in ("manual", "webhook"):
                if args.schedule_value:
                    raise ValueError(f"{schedule_type} 任务不需要 --schedule-value")
                schedule_value = None
            elif not schedule_value:
                raise ValueError(f"{schedule_type} 任务需要 --schedule-value")
            elif schedule_type == "interval":
                try:
                    if float(schedule_value) <= 0:
                        raise ValueError
                except ValueError:
                    raise ValueError("固定间隔必须是大于 0 的秒数") from None
            elif compute_next_run({"name": task["name"], "schedule_type": "cron",
                                   "schedule_value": schedule_value}) is None:
                raise ValueError("Cron 表达式无效")
            fields.update(schedule_type=schedule_type, schedule_value=schedule_value)
    except (ScriptError, ValueError) as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    if not fields:
        print("错误: 没有要修改的内容；用 autotask edit -h 查看可改项", file=sys.stderr)
        return 1

    db.update_task(task["id"], **fields)
    fresh = db.get_task(task["id"])
    if "schedule_type" in fields or "scheduled_at" in fields:
        db.update_task(task["id"], next_run_at=compute_next_run(fresh) if fresh["enabled"] else None)
        fresh = db.get_task(task["id"])
    print(f"已更新任务: {task['name']}")
    for key in fields:
        value = fresh[key]
        if key == "scheduled_at":
            value = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))
        print(f"  {key}: {value}")
    if fresh.get("next_run_at") and ("schedule_type" in fields or "scheduled_at" in fields):
        print("  下次运行: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(fresh["next_run_at"])))
    if task["running_pid"]:
        print("提示: 任务正在运行，本次运行不受影响，修改从下次运行起生效")
    return 0


def cmd_remove(args):
    cfg, cfg_path, db = _load()
    task = db.get_task_by_name(args.name) if not args.name.isdigit() else db.get_task(int(args.name))
    if not task:
        print(f"错误: 未找到任务: {args.name}", file=sys.stderr)
        return 1
    if task["running_pid"]:
        print("错误: 请先停止运行中的任务，再删除", file=sys.stderr)
        return 1
    db.delete_task(task["id"])
    print(f"已删除任务: {task['name']}")
    return 0


def cmd_enable(args, enabled):
    cfg, cfg_path, db = _load()
    task = db.get_task_by_name(args.name) if not args.name.isdigit() else db.get_task(int(args.name))
    if not task:
        print(f"错误: 未找到任务: {args.name}", file=sys.stderr)
        return 1
    if task.get("task_kind", "recurring") == "one_off":
        if not enabled and db.cancel_one_off(task["id"]):
            print(f"一次性任务 {task['name']} 已取消")
            return 0
        print("错误: 一次性任务只能在等待执行时取消，不能用 enable/disable 改变状态", file=sys.stderr)
        return 1
    db.update_task(task["id"], enabled=int(enabled))
    if enabled and task["schedule_type"] in ("cron", "interval"):
        fresh = db.get_task(task["id"])
        nxt = compute_next_run(fresh)
        db.update_task(task["id"], next_run_at=nxt)
    else:
        db.update_task(task["id"], next_run_at=None)
    print(f"任务 {task['name']} 已{'启用' if enabled else '停用'}")
    return 0


def cmd_cancel(args):
    cfg, cfg_path, db = _load()
    task = db.get_task_by_name(args.name) if not args.name.isdigit() else db.get_task(int(args.name))
    if not task:
        print(f"错误: 未找到任务: {args.name}", file=sys.stderr)
        return 1
    if task.get("task_kind", "recurring") != "one_off":
        print("错误: 只有一次性任务可以取消", file=sys.stderr)
        return 1
    if not db.cancel_one_off(task["id"]):
        print("错误: 任务不是可取消的等待状态", file=sys.stderr)
        return 1
    print(f"一次性任务 {task['name']} 已取消")
    return 0


def cmd_run(args):
    cfg, cfg_path, db = _load()
    task = db.get_task_by_name(args.name) if not args.name.isdigit() else db.get_task(int(args.name))
    if not task:
        print(f"错误: 未找到任务: {args.name}", file=sys.stderr)
        return 1
    is_one_off = task.get("task_kind", "recurring") == "one_off"
    if is_one_off and args.force:
        print("错误: 一次性任务不能用 --force 重复执行", file=sys.stderr)
        return 1
    if task["running_pid"] and not args.force:
        print(f"错误: 任务正在运行中 (pid={task['running_pid']})，用 --force 强制并发运行", file=sys.stderr)
        return 1
    extra = args.extra_args or []
    if is_one_off:
        if extra:
            print("错误: 一次性任务创建后不能追加参数", file=sys.stderr)
            return 1
        if task.get("one_off_state") in ("completed", "failed", "cancelled"):
            if not db.requeue_one_off(task["id"]):
                print("错误: 一次性任务状态已变化，请重试", file=sys.stderr)
                return 1
            task = db.get_task(task["id"])
        elif task.get("one_off_state") != "pending":
            print("错误: 一次性任务正在启动或运行中", file=sys.stderr)
            return 1
    if is_one_off and not args.wait:
        # Preserve the CLI queue semantics; next-agent claims it on the next tick.
        now = time.time()
        db.update_task(
            task["id"], scheduled_at=now, one_off_trigger="immediate",
            next_run_at=now, enabled=1,
        )
        print("一次性任务已入队，将由 autotaskd 立即在后台执行")
        return 0
    if args.wait:
        scheduler = Scheduler(cfg, db)
        if is_one_off:
            run_id = scheduler.run_one_off_now(task)
            if run_id is None:
                print("错误: 一次性任务正在启动或运行中", file=sys.stderr)
                return 1
        else:
            run_id = scheduler.run_now(task, extra_args=extra)
        print(f"已触发运行，run_id={run_id}")
        while True:
            run = db.get_run(run_id)
            if run["finished_at"]:
                print(f"完成，退出码: {run['exit_code']}")
                if run.get("log_path") and os.path.isfile(run["log_path"]):
                    with open(run["log_path"], "r", errors="replace") as f:
                        print(f.read())
                return 0 if run["exit_code"] == 0 else 1
            time.sleep(0.5)

    scheduler = Scheduler(cfg, db)
    scheduler.run_now(task, extra_args=extra)
    print(f"已触发后台执行，worker_pid={scheduler.runner.worker_pid}")
    return 0


def cmd_execute_task(args):
    """Worker owns execution and persists completion independently of the service."""
    from pathlib import Path
    from .runner import Runner
    cfg, cfg_path, db = _load()
    task = db.get_task(args.task_id)
    if not task:
        print(f"错误: 未找到任务 id={args.task_id}", file=sys.stderr)
        return 1
    try:
        extra = json.loads(args.extra_args_json)
        command = json.loads(args.command_json) if args.command_json else None
    except (TypeError, json.JSONDecodeError):
        print("错误: 无效的内部任务参数", file=sys.stderr)
        return 2
    if not isinstance(extra, list) or (command is not None and
            (not isinstance(command, list) or not all(isinstance(x, str) for x in command))):
        print("错误: 无效的内部任务参数", file=sys.stderr)
        return 2
    if args.run_id is None:
        # The documented internal command can still be invoked directly;
        # all execution goes through the same scope launcher.
        run_args = argparse.Namespace(name=str(args.task_id), force=args.force, wait=True, extra_args=extra)
        return cmd_run(run_args)
    run = db.get_run(args.run_id)
    if not run or run['task_id'] != task['id'] or run['finished_at'] is not None or not command:
        return 1
    db.update_task(task['id'], running_pid=os.getpid())
    if args.ready_file: Path(args.ready_file).touch()
    code = Runner(cfg, db).execute_run(task, args.run_id, run['log_path'], command, args.payload_file, args.cwd)
    return 0 if code == 0 else 1


def cmd_logs(args):
    cfg, cfg_path, db = _load()
    task = db.get_task_by_name(args.name) if not args.name.isdigit() else db.get_task(int(args.name))
    if not task:
        print(f"错误: 未找到任务: {args.name}", file=sys.stderr)
        return 1
    runs = db.list_runs(task_id=task["id"], limit=args.count)
    if not runs:
        print("暂无运行记录")
        return 0
    if args.latest:
        run = runs[0]
        if run.get("log_path") and os.path.isfile(run["log_path"]):
            with open(run["log_path"], "r", errors="replace") as f:
                print(f.read())
        else:
            print("日志文件不存在")
        return 0
    for r in runs:
        started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["started_at"]))
        status = "运行中" if not r["finished_at"] else f"exit={r['exit_code']}"
        print(f"run#{r['id']} {started} [{r['trigger']}] {status}  {r['log_path']}")
    return 0


def cmd_status(args):
    cfg, cfg_path, db = _load()
    print(f"配置文件: {cfg_path}")
    print(f"脚本目录: {cfg['scripts_dir']}")
    print(f"数据目录: {cfg['data_dir']}")
    print("服务: next-agent API /api/automations")
    print(f"系统时区: {system_timezone_name()}（cron 按此时区执行）")
    tasks = db.list_tasks()
    running = [t for t in tasks if t["running_pid"]]
    one_off = [t for t in tasks if t.get("task_kind", "recurring") == "one_off"]
    print(f"任务总数: {len(tasks)}（重复/常驻: {len(tasks) - len(one_off)}，一次性: {len(one_off)}），运行中: {len(running)}")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="autotask", description="自动化脚本运行工具")
    sub = p.add_subparsers(dest="command", required=True)

    pc = sub.add_parser("create", help="创建一个新脚本（可选注册为重复或一次性任务）")
    pc.add_argument("filename", help="脚本文件名（不含扩展名也可；会放入任务专属目录）")
    pc.add_argument("--type", choices=["python", "shell"], default="python", help="脚本类型")
    pc.add_argument("--description", "-d", help="脚本用途描述，写入脚本头部注释/文档字符串")
    pc.add_argument("--force", action="store_true", help="覆盖已存在的同名文件")
    pc.add_argument("--register", action="store_true", help="创建后立即注册为任务")
    pc.add_argument("--name", help="任务名/专属目录名（默认使用文件名，不含扩展名）")
    pc.add_argument("--args", help="任务默认参数，JSON 数组字符串")
    pc.add_argument("--kind", choices=["recurring", "one-off"], help="任务分类；一次性任务需配合下列选项")
    pc.add_argument("--schedule-type", dest="schedule_type", choices=["manual", "cron", "interval", "webhook"], default="manual")
    pc.add_argument("--schedule-value", dest="schedule_value", help="cron 表达式或间隔秒数")
    pc.add_argument("--once-at", help="仅一次：在本地时间执行，如 '2026-09-20 18:30'")
    pc.add_argument("--run-once", action="store_true", help="仅一次：创建后由 daemon 立即后台执行")
    pc.add_argument("--disabled", action="store_true", help="注册后不启用")
    pc.set_defaults(func=cmd_create)

    pl = sub.add_parser("list", help="列出所有任务")
    pl.add_argument("--json", action="store_true", help="以 JSON 输出")
    pl.add_argument("--group", help="按分组名称或 ID 筛选；可用“未分组”或“所有任务”")
    pl.set_defaults(func=cmd_list)

    pgr = sub.add_parser("groups", help="查询、创建、重命名、删除分组及移动任务")
    gr = pgr.add_subparsers(dest="group_command", required=True)
    gl = gr.add_parser("list", help="列出分组及任务数")
    gl.add_argument("--json", action="store_true")
    gc = gr.add_parser("create", help="创建分组")
    gc.add_argument("name")
    gn = gr.add_parser("rename", help="重命名分组")
    gn.add_argument("group", help="分组名称或 ID")
    gn.add_argument("name", help="新名称")
    gd = gr.add_parser("delete", help="删除分组，任务转为未分组")
    gd.add_argument("group", help="分组名称或 ID")
    gm = gr.add_parser("move", help="将任务移入分组")
    gm.add_argument("task", help="任务名称或 ID")
    gm.add_argument("group", help="分组名称或 ID")
    gu = gr.add_parser("ungroup", help="将任务移至未分组")
    gu.add_argument("task", help="任务名称或 ID")
    for parser in (gl, gc, gn, gd, gm, gu):
        parser.set_defaults(func=cmd_groups)

    pa = sub.add_parser("add", help="将任务专属目录中的已存在脚本注册为任务")
    pa.add_argument("name", help="任务名")
    pa.add_argument("script", help="脚本文件名（相对于 scripts 目录）")
    pa.add_argument("--description", "-d", help="任务描述（独立于脚本内容）")
    pa.add_argument("--args", help="任务默认参数，JSON 数组字符串")
    pa.add_argument("--kind", choices=["recurring", "one-off"], help="任务分类；一次性任务需配合下列选项")
    pa.add_argument("--schedule-type", dest="schedule_type", choices=["manual", "cron", "interval", "webhook"], default="manual")
    pa.add_argument("--schedule-value", dest="schedule_value", help="cron 表达式或间隔秒数")
    pa.add_argument("--once-at", help="仅一次：在本地时间执行，如 '2026-09-20 18:30'")
    pa.add_argument("--run-once", action="store_true", help="仅一次：由 daemon 立即后台执行")
    pa.add_argument("--disabled", action="store_true", help="创建后不启用")
    pa.set_defaults(func=cmd_add)

    pedit = sub.add_parser("edit", help="修改已有任务的描述、脚本、参数或调度（保留运行记录）")
    pedit.add_argument("name", help="任务名或 ID")
    pedit.add_argument("--description", "-d", help="新的任务描述；传空字符串清空")
    pedit.add_argument("--script", help="新的脚本路径（相对 scripts 目录，须在任务专属目录内）")
    pedit.add_argument("--args", help="替换默认参数，JSON 数组字符串")
    pedit.add_argument("--clear-args", action="store_true", help="清空默认参数")
    pedit.add_argument("--schedule-type", dest="schedule_type", choices=["manual", "cron", "interval", "webhook"],
                       help="重复任务：新的调度方式")
    pedit.add_argument("--schedule-value", dest="schedule_value", help="重复任务：新的 cron 表达式或间隔秒数")
    pedit.add_argument("--once-at", help="等待中的一次性任务：改到本地时间执行，如 '2026-09-20 18:30'")
    pedit.set_defaults(func=cmd_edit)

    pr = sub.add_parser("remove", help="删除任务（按名称或 id）")
    pr.add_argument("name")
    pr.set_defaults(func=cmd_remove)

    pe = sub.add_parser("enable", help="启用任务")
    pe.add_argument("name")
    pe.set_defaults(func=lambda a: cmd_enable(a, True))

    pd = sub.add_parser("disable", help="停用任务")
    pd.add_argument("name")
    pd.set_defaults(func=lambda a: cmd_enable(a, False))

    px = sub.add_parser("cancel", help="取消尚未开始的一次性任务")
    px.add_argument("name")
    px.set_defaults(func=cmd_cancel)

    pu = sub.add_parser("run", help="立即运行任务（后台或等待完成）")
    pu.add_argument("name")
    pu.add_argument("--wait", action="store_true", help="等待运行完成并打印日志")
    pu.add_argument("--force", action="store_true", help="即使任务正在运行也强制并发执行")
    pu.add_argument("extra_args", nargs="*", help="附加到脚本的额外参数（如需要，用 -- 分隔）")
    pu.set_defaults(func=cmd_run)

    # Intentionally undocumented: spawned only by `autotask run` to provide a
    # durable background worker for short-lived CLI invocations.
    pw = sub.add_parser("_execute-task", help=argparse.SUPPRESS)
    pw.add_argument("task_id", type=int)
    pw.add_argument("--extra-args-json", required=True)
    pw.add_argument("--force", action="store_true")
    pw.add_argument("--run-id", type=int, help=argparse.SUPPRESS)
    pw.add_argument("--command-json", help=argparse.SUPPRESS)
    pw.add_argument("--cwd", help=argparse.SUPPRESS)
    pw.add_argument("--ready-file", help=argparse.SUPPRESS)
    pw.add_argument("--payload-file", help=argparse.SUPPRESS)
    pw.set_defaults(func=cmd_execute_task)

    pg = sub.add_parser("logs", help="查看任务运行日志")
    pg.add_argument("name")
    pg.add_argument("--count", type=int, default=10, help="显示最近 N 条运行记录")
    pg.add_argument("--latest", action="store_true", help="打印最近一次运行的完整日志内容")
    pg.set_defaults(func=cmd_logs)

    ps = sub.add_parser("status", help="查看系统状态")
    ps.set_defaults(func=cmd_status)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        sys.exit(args.func(args) or 0)
    except ScriptError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
