"""Persistent schedules and the single scheduler loop."""
import asyncio
import json
import time
from datetime import datetime
from typing import Literal
from uuid import uuid4

from croniter import croniter
from fastapi import HTTPException
from pydantic import Field, StrictBool
from ..paths import atomic_write
from . import Input, Prompt, mcp_tool


class Target(Input):
    module: Literal['agents', 'more_agents'] = 'agents'
    agent_id: str = ''
    session: str = Field(default='new', min_length=1)
    cwd: str = ''


class Create(Prompt):
    title: str = ''
    cron: str | None = None
    at: str | None = None
    target: Target = Field(default_factory=Target)
    model: str = ''
    effort: str = ''


class ScheduleInput(Create):
    enabled: StrictBool = True


class ScheduleId(Input):
    id: str = Field(min_length=1)


def next_run(values, now):
    if values['cron']:
        return croniter(values['cron'], datetime.fromtimestamp(now)).get_next(datetime).timestamp()
    return datetime.fromisoformat(values['at']).timestamp()


class Schedules:
    def __init__(self, builtin):
        self.builtin = builtin
        self.path = builtin.core.paths.root / 'builtin' / 'schedules.json'
        self.entries = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.changed = asyncio.Event()
        self.launching = set()

    def save(self):
        atomic_write(self.path, json.dumps(self.entries, ensure_ascii=False, indent=2))
        self.changed.set()
        self.builtin.core.emit({'type': 'schedules_changed', 'module': 'builtin'})

    def get(self, sid, caller=None):
        if sid not in self.entries: raise KeyError('Schedule not found')
        schedule = self.entries[sid]
        owner = schedule['created_by']
        if caller and (not owner or (owner['module'], owner['agent_id'])!=(caller['module'], caller['agent_id'])):
            raise ValueError('Schedule belongs to another agent')
        return schedule

    def validate(self, data, caller=None, future=True):
        values = ScheduleInput.model_validate(data).model_dump()
        if values['target'].get('module') == 'agents' and not values['target'].get('cwd'): values['target'].pop('cwd', None)
        if (values['cron'] is None)==(values['at'] is None): raise ValueError('Exactly one of cron or at is required')
        if values['cron'] is not None:
            if len(values['cron'].split())!=5 or not croniter.is_valid(values['cron']):
                raise ValueError('cron must have five valid fields')
        else:
            if 'T' not in values['at'] and ' ' not in values['at']: raise ValueError('at must be a local datetime')
            at = datetime.fromisoformat(values['at'])
            if at.tzinfo is not None: raise ValueError('at must be a local datetime without a timezone')
        upcoming = next_run(values, time.time())
        if values['at'] and future and upcoming<=time.time(): raise ValueError('at must be in the future')
        target = values['target']
        if target['module'] == 'more_agents' and target['session'] == 'new' and not target.get('cwd'):
            raise ValueError('cwd is required for a new More Agents schedule')
        if target['module'] == 'agents' and target.get('cwd'):
            raise ValueError('cwd is only valid for More Agents')
        if not target['agent_id']:
            if not caller: raise ValueError('target.agent_id is required')
            target['agent_id'] = caller['agent_id']
        if target['session']=='this':
            if not caller or (target['module'], target['agent_id'])!=(caller['module'], caller['agent_id']):
                raise ValueError('this is only valid for the calling agent')
            target['session'] = caller['session_id']
        self.builtin.target(target['module'], target['agent_id'], target['session'])
        return values, upcoming if values['enabled'] else None

    def create(self, data, caller=None):
        values, upcoming = self.validate(data, caller)
        sid = 's_'+uuid4().hex[:12]
        schedule = dict(id=sid, **values, created_by=caller, created_at=time.time(), next_run=upcoming,
                        last_run=None, last_result=None)
        self.entries[sid] = schedule
        self.save()
        return schedule

    def update(self, sid, data):
        schedule = self.get(sid)
        if set(data)-ScheduleInput.model_fields.keys(): raise ValueError('Unknown schedule field')
        reset = bool({'cron', 'at'} & data.keys()) or data.get('enabled') is True and not schedule['enabled']
        values, upcoming = self.validate({**{k: schedule[k] for k in ScheduleInput.model_fields}, **data}, future=reset)
        schedule.update(values)
        if reset or not schedule['enabled']: schedule['next_run'] = upcoming
        self.save()
        return schedule

    def delete(self, sid, caller=None):
        self.get(sid, caller)
        del self.entries[sid]
        self.save()
        return {'ok': True}

    async def fire(self, sid, scheduled=False):
        schedule = self.get(sid)
        now = time.time()
        schedule['last_run'] = now
        if scheduled:
            schedule['next_run'] = next_run(schedule, now) if schedule['cron'] else None
            if schedule['at']: schedule['enabled'] = False
        target = schedule['target']
        session_id = None
        try:
            self.builtin.target(target['module'], target['agent_id'], target['session'])
        except (KeyError, ValueError, HTTPException) as exc:
            schedule.update(enabled=False, next_run=None, last_result=dict(session_id=None, is_error=True, error=str(exc)))
            self.save()
            raise ValueError('Schedule target no longer exists') from exc
        try:
            session_id, result = await self.builtin.start(target['module'], target['agent_id'], schedule['prompt'],
                session_id=None if target['session']=='new' else target['session'], origin='schedule',
                title=schedule['title'] or 'Scheduled: '+schedule['prompt'][:40],
                model=schedule['model'], effort=schedule['effort'], **({'cwd': target['cwd']} if target.get('cwd') else {}))
        except Exception as exc:
            schedule['last_result'] = dict(session_id=session_id, is_error=True, error=str(exc))
            self.save()
            raise
        schedule['last_result'] = None
        self.save()
        self.builtin.background(self.finish(schedule, session_id, result, now))
        return {'session_id': session_id}

    async def finish(self, schedule, sid, result, run):
        try: value = await result
        except Exception as exc: value = dict(is_error=True, error=str(exc))
        if self.entries.get(schedule['id']) is schedule and schedule['last_run']==run:
            schedule['last_result'] = dict(session_id=sid, is_error=value.get('is_error', False), error=value.get('error'))
            self.save()

    async def run_due(self, startup=False):
        now = time.time()
        for schedule in list(self.entries.values()):
            due = schedule['next_run']
            if not schedule['enabled'] or due is None or due>now or schedule['id'] in self.launching: continue
            if startup and now-due>=3600:
                schedule['next_run'] = next_run(schedule, now) if schedule['cron'] else None
                if schedule['at']: schedule['enabled'] = False
                self.save()
                continue
            self.launching.add(schedule['id'])
            self.builtin.background(self.launch(schedule['id']))

    async def launch(self, sid):
        try: await self.fire(sid, scheduled=True)
        except Exception: pass  # fire persisted the error; other schedules still run.
        finally: self.launching.discard(sid)

    async def run(self):
        await self.run_due(startup=True)
        while True:
            self.changed.clear()
            await self.run_due()
            upcoming = [s['next_run'] for s in self.entries.values()
                        if s['enabled'] and s['next_run'] is not None and s['id'] not in self.launching]
            delay = max(0, min(30, min(upcoming)-time.time())) if upcoming else 30
            try: await asyncio.wait_for(self.changed.wait(), delay)
            except TimeoutError: pass

    def tools(self, caller):
        async def create(args): return self.create(args.model_dump(), caller)
        async def listing(args):
            return [s for s in self.entries.values() if s['created_by'] and
                    (s['created_by']['module'], s['created_by']['agent_id'])==(caller['module'], caller['agent_id'])]
        async def delete(args): return self.delete(args.id, caller)
        return [mcp_tool('schedule_create', 'Schedule a prompt using exactly one of cron (five fields) or at (local datetime).', Create, create),
                mcp_tool('schedule_list', 'List schedules created by this agent.', Input, listing),
                mcp_tool('schedule_delete', 'Delete a schedule created by this agent.', ScheduleId, delete)]
