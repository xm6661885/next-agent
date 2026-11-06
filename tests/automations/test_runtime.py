import os
import signal
import subprocess
import time
from pathlib import Path
from unittest.mock import Mock
import pytest
from server.automations.runner import Runner, ScriptError, launch_worker
from server.automations.scheduler import Scheduler, compute_next_run


def test_local_cron_and_invalid_schedules(monkeypatch):
    monkeypatch.setenv('TZ','Asia/Singapore')
    # 2024-01-01 00:00 UTC = 08:00 Singapore; next 09:00 is one hour away.
    now=1704067200
    task={'name':'cron','schedule_type':'cron','schedule_value':'0 9 * * *'}
    assert compute_next_run(task,now)==now+3600
    task['schedule_value']='bad'; assert compute_next_run(task,now) is None
    assert compute_next_run({'schedule_type':'interval','schedule_value':'bad'},now) is None
    assert compute_next_run({'task_kind':'one_off','enabled':0,'one_off_state':'pending'},now) is None
    assert compute_next_run({'task_kind':'one_off','enabled':1,'one_off_state':'pending','scheduled_at':None},now) is None


def test_misfire_initial_cache_and_overlap(auto,script,monkeypatch):
    monkeypatch.setenv('TZ','UTC')
    now=1704067200
    monkeypatch.setattr('server.automations.scheduler.time.time',lambda:now)
    cron=auto.db.create_task('cron',script('cron'),[],'cron','* * * * *')
    interval=auto.db.create_task('interval',script('interval'),[],'interval','10')
    disabled=auto.db.create_task('disabled',script('disabled'),[],'cron','* * * * *',enabled=False)
    auto.db.update_task(cron,next_run_at=now-3600)
    auto.db.update_task(interval,created_at=now-20,next_run_at=None)
    scheduler=auto.manager.scheduler
    launched=Mock(); monkeypatch.setattr(scheduler.runner,'run_task',launched)
    scheduler._tick()
    assert [c.args[0]['id'] for c in launched.call_args_list]==[cron]
    assert auto.db.get_task(cron)['next_run_at']==now+60
    assert auto.db.get_task(interval)['next_run_at']==now
    scheduler._tick()
    assert [c.args[0]['id'] for c in launched.call_args_list]==[cron,interval]
    assert auto.db.get_task(disabled)['next_run_at'] is None
    auto.db.update_task(cron,running_pid=os.getpid(),next_run_at=now-1)
    launched.reset_mock(); scheduler._tick()
    assert auto.db.get_task(cron)['next_run_at']==now-1
    assert all(c.args[0]['id']!=cron for c in launched.call_args_list)


def test_recovery_keeps_live_and_permission_denied_workers(auto,script,monkeypatch):
    ids=[]; runs=[]
    for name,pid in [('live',101),('denied',102),('dead',103),('unstarted',None)]:
        tid=auto.db.create_task(name,script(name,'once'),[],'once',None,enabled=False,
            task_kind='one_off',scheduled_at=1,one_off_state='running',one_off_trigger='immediate')
        auto.db.update_task(tid,running_pid=pid)
        ids.append(tid); runs.append(auto.db.create_run(tid,'once_immediate','log'))
    orphan=auto.db.create_task('orphan',script('orphan','once'),[],'once',None,
        task_kind='one_off',scheduled_at=1,one_off_state='running')
    def kill(pid,sig):
        if pid==102: raise PermissionError
        if pid==103: raise ProcessLookupError
    monkeypatch.setattr('server.automations.db.os.kill',kill)
    assert auto.db.recover_interrupted_runs()==3
    for tid,rid in zip(ids[:2],runs[:2]):
        assert auto.db.get_task(tid)['one_off_state']=='running'
        assert auto.db.get_run(rid)['finished_at'] is None
    for tid,rid in zip(ids[2:],runs[2:]):
        assert auto.db.get_task(tid)['one_off_state']=='failed'
        assert auto.db.get_run(rid)['exit_code']==-1
    assert auto.db.get_task(orphan)['one_off_state']=='failed'


def test_scope_launcher_and_environment(tmp_path,monkeypatch):
    ready=tmp_path/'ready'; proc=Mock(pid=123)
    seen=[]
    def popen(argv,**kw): seen.append((argv,kw)); ready.touch(); return proc
    monkeypatch.setattr('server.automations.runner.subprocess.Popen',popen)
    monkeypatch.delenv('XDG_RUNTIME_DIR',raising=False); monkeypatch.delenv('DBUS_SESSION_BUS_ADDRESS',raising=False)
    assert launch_worker(['python','worker'],2,7,tmp_path,ready)==123
    argv,kw=seen[0]
    assert argv==['systemd-run','--user','--scope','--collect','--quiet','--unit','autotask-2-7','--','python','worker']
    assert kw['env']['XDG_RUNTIME_DIR']==f'/run/user/{os.getuid()}'
    assert kw['env']['DBUS_SESSION_BUS_ADDRESS']==f'unix:path=/run/user/{os.getuid()}/bus'
    assert kw['start_new_session'] and kw['env']['NEXT_AGENT_DATA']==str(tmp_path)
    assert not ready.exists()


def test_scope_exit_failure_falls_back(tmp_path,monkeypatch,caplog):
    ready=tmp_path/'ready'; rejected=Mock(); rejected.poll.return_value=1
    accepted=Mock(pid=456); calls=[]
    def popen(argv,**kw):
        calls.append(argv)
        if len(calls)==1: return rejected
        ready.touch(); return accepted
    monkeypatch.setattr('server.automations.runner.subprocess.Popen',popen)
    assert launch_worker(['worker'],2,7,tmp_path,ready)==456
    assert calls[1]==['worker']
    assert 'using detached worker' in caplog.text


def test_real_fallback_worker_payload_pid_log_and_exit(auto,script,monkeypatch):
    real_popen=subprocess.Popen
    def fallback(argv,**kw):
        if argv[0]=='systemd-run': raise FileNotFoundError('test fallback')
        return real_popen(argv,**kw)
    monkeypatch.setattr('server.automations.runner.subprocess.Popen',fallback)
    rel=script(content='echo "pid=$$"\npwd\ncat\nsleep .3\nexit 7\n')
    tid=auto.db.create_task('job',rel,[],'webhook',None)
    rid=auto.manager.runner.run_task(auto.db.get_task(tid),trigger='webhook',stdin_data=b'{"original":  true}\n')
    deadline=time.monotonic()+10; pids=[]
    while time.monotonic()<deadline:
        pids.append(auto.db.get_task(tid)['running_pid'])
        run=auto.db.get_run(rid)
        if run['finished_at'] is not None: break
        time.sleep(.02)
    assert run['finished_at'] is not None and run['exit_code']==7
    log=Path(run['log_path']).read_text()
    assert '{"original":  true}' in log
    assert str((auto.scripts/rel).parent) in log
    assert any(pid and f'pid={pid}\n' in log for pid in pids)
    assert auto.db.get_task(tid)['running_pid'] is None
    assert list((auto.root/'automations/tmp').iterdir())==[]


def test_stop_uses_process_group_and_reconcile(auto,script,monkeypatch):
    tid=auto.db.create_task('job',script(),[],'manual',None)
    rid=auto.db.create_run(tid,'manual','log'); auto.db.update_task(tid,running_pid=42)
    kill=Mock(); monkeypatch.setattr('server.automations.runner.os.killpg',kill)
    assert auto.manager.runner.stop_task(auto.db.get_task(tid))
    kill.assert_called_once_with(42,signal.SIGTERM)
    kill.side_effect=ProcessLookupError
    assert not auto.manager.runner.stop_task(auto.db.get_task(tid))
    assert auto.db.get_task(tid)['running_pid'] is None
    assert auto.db.get_run(rid)['finished_at'] is not None
    assert auto.db.get_run(rid)['exit_code'] is None


def test_claim_failure_and_script_containment(auto,script,monkeypatch):
    rel=script('one','once')
    tid=auto.db.create_task('one',rel,[],'once',None,task_kind='one_off',scheduled_at=1,one_off_state='pending')
    (auto.scripts/rel).unlink()
    with pytest.raises(ScriptError): auto.manager.scheduler.run_one_off_now(auto.db.get_task(tid))
    assert auto.db.get_task(tid)['one_off_state']=='failed'
    outside=auto.root/'outside.sh'; outside.write_text('echo bad')
    script('job'); (auto.scripts/'cron/job/link.sh').symlink_to(outside)
    tid=auto.db.create_task('job','cron/job/link.sh',[],'manual',None)
    with pytest.raises(ScriptError): auto.manager.runner.run_task(auto.db.get_task(tid))
    assert auto.db.list_runs(tid)==[]


def test_cli_wait_works_without_service(auto,script,cli,monkeypatch):
    real_popen=subprocess.Popen
    def fallback(argv,**kw):
        if argv[0]=='systemd-run': raise FileNotFoundError('test fallback')
        return real_popen(argv,**kw)
    monkeypatch.setattr('server.automations.runner.subprocess.Popen',fallback)
    auto.db.create_task('job',script(content='echo waited\nexit 0\n'),[],'manual',None)
    code,out=cli('run','job','--wait')
    assert code==0
    assert '已触发运行，run_id=1' in out and '完成，退出码: 0' in out and 'waited\n' in out
    assert auto.db.list_runs()[0]['exit_code']==0


@pytest.mark.parametrize('python_dir_exists',[True,False])
@pytest.mark.parametrize('lang',['custom.UTF-8',None])
def test_worker_task_path_and_inherited_environment(auto,script,monkeypatch,python_dir_exists,lang):
    python_dir=auto.root/'task-venv/bin'
    if python_dir_exists:
        python_dir.mkdir(parents=True)
        for name in ('python','python3'):
            (python_dir/name).write_text('#!/bin/sh\necho task-venv\n')
            (python_dir/name).chmod(0o755)
    cfg=dict(auto.cfg,python_bin=str(python_dir/'python'))
    monkeypatch.setenv('PATH','/usr/bin:/bin')
    if lang is None: monkeypatch.delenv('LANG',raising=False)
    else: monkeypatch.setenv('LANG',lang)
    monkeypatch.setenv('LC_ALL','C.UTF-8')
    seen=[]; real_popen=subprocess.Popen
    def popen(*args,**kw):
        seen.append(kw['env'])
        return real_popen(*args,**kw)
    monkeypatch.setattr('server.automations.runner.subprocess.Popen',popen)
    rel=script(content='command -v python3\n'+('python3\npython\n' if python_dir_exists else ''))
    task_id=auto.db.create_task('env',rel,[],'manual',None)
    log=auto.root/'env.log'; rid=auto.db.create_run(task_id,'manual',str(log))
    assert Runner(cfg,auto.db).execute_run(auto.db.get_task(task_id),rid,log,['/bin/bash',str(auto.scripts/rel)])==0
    assert seen[0]['PATH']==(str(python_dir)+':' if python_dir_exists else '')+'/usr/bin:/bin'
    assert seen[0].get('LANG')==lang and seen[0]['LC_ALL']=='C.UTF-8'
    if python_dir_exists: assert log.read_text().count('task-venv\n')==2
