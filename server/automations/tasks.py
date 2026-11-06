"""Task input validation and script picker, shared by the JSON API."""
import json
import math
import os
import time
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .cli import (_task_folder_name, _validate_script_layout, _parse_one_off_time,
                  PY_TEMPLATE, SH_TEMPLATE)
from .scheduler import compute_next_run


class CreateTask(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str
    description: str = ''
    script: str = ''
    args: list[str] = Field(default_factory=list)
    task_kind: Literal['recurring', 'one_off'] = 'recurring'
    schedule_type: Literal['manual', 'cron', 'interval', 'webhook'] = 'manual'
    schedule_value: str | None = None
    enabled: bool = True
    one_off_trigger: Literal['immediate', 'scheduled'] = 'immediate'
    scheduled_at: float | None = Field(default=None, allow_inf_nan=False)
    scheduled_at_local: str | None = None
    create_script: Literal['python', 'shell'] | None = None


class EditTask(BaseModel):
    model_config = ConfigDict(extra='forbid')
    description: str | None = None
    script: str | None = None
    args: list[str] | None = None
    schedule_type: Literal['manual', 'cron', 'interval', 'webhook'] | None = None
    schedule_value: str | None = None
    one_off_trigger: Literal['immediate', 'scheduled'] | None = None
    scheduled_at: float | None = Field(default=None, allow_inf_nan=False)
    scheduled_at_local: str | None = None


def schedule_fields(name, kind, body, existing=None):
    old = existing or {}
    if kind == 'one_off':
        if existing and any(k in body for k in ('schedule_type', 'schedule_value')):
            raise ValueError('一次性任务没有 cron/间隔调度')
        trigger = body.get('one_off_trigger', old.get('one_off_trigger', 'immediate'))
        if 'scheduled_at' in body or 'scheduled_at_local' in body:
            trigger = body.get('one_off_trigger', 'scheduled')
        if trigger == 'immediate': due = time.time()
        elif body.get('scheduled_at_local'):
            due = _parse_one_off_time(body['scheduled_at_local'])
        else:
            due = body.get('scheduled_at', old.get('scheduled_at'))
            if due is None or due <= time.time(): raise ValueError('一次性定时时间必须晚于当前时间')
        return dict(schedule_type='once', schedule_value=None, scheduled_at=due, one_off_trigger=trigger)
    if existing and any(k in body for k in ('scheduled_at', 'scheduled_at_local', 'one_off_trigger')):
        raise ValueError('一次性选项只适用于一次性任务')
    st = body.get('schedule_type', old.get('schedule_type', 'manual'))
    sv = body.get('schedule_value', old.get('schedule_value') if st == old.get('schedule_type') else None)
    if st in ('manual', 'webhook'): sv = None
    elif not sv: raise ValueError(f'{st} 任务需要调度值')
    elif st == 'interval':
        try: value = float(sv)
        except ValueError: raise ValueError('固定间隔必须是大于 0 的秒数') from None
        if not math.isfinite(value) or value <= 0: raise ValueError('固定间隔必须是大于 0 的秒数')
    elif compute_next_run({'name': name, 'schedule_type': st, 'schedule_value': sv}) is None:
        raise ValueError('Cron 表达式无效')
    return dict(schedule_type=st, schedule_value=sv)


def description(value):
    value = value.strip()
    if len(value) > 1000: raise ValueError('任务说明不能超过 1000 个字符')
    return value


def create_fields(cfg, body):
    values = body.model_dump(exclude_none=True)
    # Default None timestamps must not override the immediate trigger.
    name = _task_folder_name(body.name)
    fields = dict(name=name, description=description(body.description), args=body.args,
                  task_kind=body.task_kind, enabled=body.enabled)
    fields.update(schedule_fields(name, body.task_kind, values))
    if body.task_kind == 'one_off': fields.update(enabled=True, one_off_state='pending')
    if body.create_script:
        if body.script: raise ValueError('script 和 create_script 只能选一个')
        root = 'once' if body.task_kind == 'one_off' else 'cron'
        suffix = '.py' if body.create_script == 'python' else '.sh'
        script = f'{root}/{name}/{name}{suffix}'
        dest = Path(cfg['scripts_dir']) / script
        allowed = Path(cfg['scripts_dir']).resolve()
        if not dest.resolve().is_relative_to(allowed): raise ValueError('script path escapes scripts_dir')
        if dest.exists(): raise ValueError('脚本文件已存在')
        dest.parent.mkdir(parents=True, exist_ok=True)
        template = PY_TEMPLATE if body.create_script == 'python' else SH_TEMPLATE
        dest.write_text(template.format(desc=fields['description'] or dest.name, name=dest.name))
        dest.chmod(dest.stat().st_mode | 0o111)
    else: script = body.script.strip()
    _validate_script_layout(cfg['scripts_dir'], script, body.task_kind, name)
    fields['script'] = script
    return fields


def edit_fields(cfg, task, body):
    values = body.model_dump(exclude_unset=True)
    if not values: raise ValueError('没有要修改的内容')
    if any(value is None for key, value in values.items() if key != 'schedule_value'):
        raise ValueError('修改字段不能为 null')
    if task['task_kind'] == 'one_off' and task['one_off_state'] != 'pending':
        raise ValueError('一次性任务只能在等待执行时编辑')
    fields = {}
    if 'description' in values: fields['description'] = description(body.description)
    if 'args' in values: fields['args'] = body.args
    if 'script' in values:
        script = body.script.strip()
        _validate_script_layout(cfg['scripts_dir'], script, task['task_kind'], task['name'])
        fields['script'] = script
    if values.keys() & {'schedule_type','schedule_value','scheduled_at','scheduled_at_local','one_off_trigger'}:
        fields.update(schedule_fields(task['name'], task['task_kind'], values, task))
    return fields


def view(task):
    return {**task, 'running': bool(task['running_pid']), 'args_list': json.loads(task['args'])}


def list_scripts(scripts_dir, registered_scripts=None):
    groups = {'recurring': [], 'one_off': []}
    for kind, root in (('recurring', 'cron'), ('one_off', 'once')):
        for directory, dirs, files in os.walk(Path(scripts_dir) / root):
            dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
            for name in sorted(files):
                path = Path(directory) / name
                if name.startswith('.') or not path.is_file(): continue
                if path.suffix not in ('.py', '.sh') and not os.access(path, os.X_OK): continue
                relative = path.relative_to(scripts_dir).as_posix()
                if registered_scripts is not None and relative not in registered_scripts and path.stem != path.parent.name: continue
                groups[kind].append(relative)
    return groups
