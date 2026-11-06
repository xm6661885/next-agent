"""Pytest port of AutoTask's edit, groups and one_off unittest suites."""
import json
import sqlite3
import time
from unittest.mock import Mock
import pytest
from server.automations.db import DB
from server.automations.scheduler import Scheduler
from server.automations.tasks import list_scripts


@pytest.fixture
def job(auto,script):
    tid=auto.db.create_task('job',script(),['--old'],'cron','0 2 * * *')
    script(filename='other.py',content='print(1)\n')
    auto.db.create_run(tid,'manual','x.log')
    return tid


def test_edit_args_description_and_keep_runs(auto,job,cli):
    assert cli('edit','job','--clear-args','-d','新说明')[0]==0
    task=auto.db.get_task(job)
    assert (json.loads(task['args']),task['description'],task['schedule_value'])==([], '新说明', '0 2 * * *')
    assert len(auto.db.list_runs(job))==1
    assert cli('edit',str(job),'--args','["-v"]')[0]==0
    assert json.loads(auto.db.get_task(job)['args'])==['-v']


def test_edit_schedule_recomputes_next_run(auto,job,cli):
    assert cli('edit','job','--schedule-type','interval','--schedule-value','600')[0]==0
    task=auto.db.get_task(job)
    assert (task['schedule_type'],task['schedule_value'])==('interval','600')
    assert task['next_run_at'] is not None
    assert cli('edit','job','--schedule-type','webhook')[0]==0
    task=auto.db.get_task(job)
    assert (task['schedule_type'],task['schedule_value'],task['next_run_at'])==('webhook',None,None)


def test_edit_script_stays_in_task_dir(auto,job,cli):
    assert cli('edit','job','--script','cron/job/other.py')[0]==0
    assert auto.db.get_task(job)['script']=='cron/job/other.py'
    assert cli('edit','job','--script','cron/elsewhere/x.py')[0]==1


@pytest.mark.parametrize('words', [('--schedule-type','cron','--schedule-value','bad cron'),
    ('--schedule-type','interval','--schedule-value','-1'), ('--args','{"a":1}'),
    ('--args','[]','--clear-args'), ('--once-at','2099-01-01 00:00'), ()])
def test_edit_rejects_invalid_input(auto,job,cli,words):
    assert cli('edit','job',*words)[0]==1
    assert cli('edit','missing','-d','x')[0]==1
    assert json.loads(auto.db.get_task(job)['args'])==['--old']


def one_off(auto,script,name='later',**kw):
    options=dict(task_kind='one_off',scheduled_at=time.time()+3600,one_off_trigger='scheduled',one_off_state='pending')
    options.update(kw)
    return auto.db.create_task(name,script(name,'once'),[],'once',None,**options)


def test_edit_pending_one_off_time(auto,script,cli):
    tid=one_off(auto,script)
    assert cli('edit','later','--once-at','2099-01-01 08:00')[0]==0
    task=auto.db.get_task(tid); assert task['next_run_at']==task['scheduled_at']
    assert cli('edit','later','--schedule-type','manual')[0]==1
    auto.db.cancel_one_off(tid)
    assert cli('edit','later','-d','x')[0]==1


def test_group_lifecycle_preserves_task_and_script(auto,script):
    tid=auto.db.create_task('job',script(),[],'manual',None); old=auto.db.get_task(tid)
    assert old['group_id'] is None
    gid=auto.db.create_group('工作'); auto.db.move_task(tid,gid)
    assert auto.db.list_tasks()[0]['group_name']=='工作'
    auto.db.rename_group(gid,'项目'); assert auto.db.list_groups()[0]['task_count']==1
    assert auto.db.delete_group(gid)==1
    assert auto.db.get_task(tid)['script']==old['script']
    assert auto.db.get_task(tid)['group_id'] is None
    with pytest.raises(ValueError): auto.db.move_task(tid,gid)
    with pytest.raises(ValueError): auto.db.create_group('未分组')


def test_cli_and_web_share_group_state(auto,script,cli):
    tid=auto.db.create_task('job',script(),[],'manual',None)
    assert cli('groups','create','运维')[0]==0
    assert cli('groups','move','job','运维')[0]==0
    assert 'job' in cli('list','--group','运维')[1]
    assert auto.client.get('/api/automations/groups').json()[0]['task_count']==1
    assert auto.client.delete(f'/api/automations/tasks/{tid}/group').status_code==200
    assert auto.db.get_task(tid)['group_id'] is None


def test_web_group_management(auto,script):
    client=auto.client; base='/api/automations/groups'
    created=client.post(base,json={'name':'工作'}); assert created.status_code==201
    gid=created.json()['id']
    assert client.post(base,json={'name':'工作'}).status_code==422
    assert client.patch(f'{base}/{gid}',json={'name':'项目'}).json()['name']=='项目'
    tid=auto.db.create_task('job',script(),[],'manual',None)
    assert client.post(f'{base}/{gid}/tasks/{tid}').status_code==200
    assert client.delete(f'{base}/{gid}').json()['moved']==1
    assert client.patch(f'{base}/{gid}',json={'name':'项目'}).status_code==404


def test_v3_migrates_groups(auto):
    with sqlite3.connect(auto.db.path) as conn:
        conn.execute('PRAGMA user_version=3')
        conn.execute("INSERT INTO tasks(name,script,created_at,updated_at) VALUES ('old','old.py',1,1)")
        conn.execute('DROP INDEX idx_tasks_group_id'); conn.execute('ALTER TABLE tasks DROP COLUMN group_id')
    db=DB(auto.cfg['data_dir'])
    assert db.get_task_by_name('old')['group_id'] is None
    assert db.list_groups()==[]


def test_v1_migrates_one_off_and_description(tmp_path):
    with sqlite3.connect(tmp_path/'autotask.db') as conn:
        conn.executescript('''CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT UNIQUE NOT NULL,
        script TEXT NOT NULL,args TEXT NOT NULL DEFAULT '[]',schedule_type TEXT NOT NULL DEFAULT 'manual',
        schedule_value TEXT,enabled INTEGER NOT NULL DEFAULT 1,created_at REAL NOT NULL,updated_at REAL NOT NULL,
        last_run_at REAL,next_run_at REAL,running_pid INTEGER);
        CREATE TABLE runs(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id INTEGER NOT NULL,started_at REAL NOT NULL,
        finished_at REAL,exit_code INTEGER,trigger TEXT NOT NULL DEFAULT 'manual',log_path TEXT);
        PRAGMA user_version=1;
        INSERT INTO tasks(name,script,created_at,updated_at) VALUES ('legacy','legacy.py',1,1);''')
    task=DB(tmp_path).get_task_by_name('legacy')
    assert task['task_kind']=='recurring' and task['description']=='' and 'one_off_state' in task


def test_due_one_off_exactly_once(auto,script,monkeypatch):
    tid=one_off(auto,script,scheduled_at=time.time()-1)
    runner=auto.manager.runner
    def finish(task,**kwargs):
        rid=auto.db.create_run(tid,kwargs['trigger'],'log'); auto.db.finish_run(rid,0); auto.db.complete_one_off(tid,0)
        return rid
    monkeypatch.setattr(runner,'run_task',Mock(side_effect=finish))
    auto.manager.scheduler._tick(); auto.manager.scheduler._tick()
    assert runner.run_task.call_count==1
    assert auto.db.get_task(tid)['one_off_state']=='completed'
    assert auto.db.get_task(tid)['enabled']==0
    assert auto.manager.scheduler.run_one_off_now(auto.db.get_task(tid)) is None


def test_cancel_and_requeue_are_atomic(auto,script):
    tid=one_off(auto,script)
    assert auto.db.cancel_one_off(tid)
    assert not auto.db.cancel_one_off(tid)
    assert auto.db.claim_one_off(tid,allow_early=True) is None
    assert auto.db.requeue_one_off(tid)
    assert not auto.db.requeue_one_off(tid)
    task=auto.db.get_task(tid)
    assert (task['one_off_state'],task['enabled'],task['one_off_trigger'])==('pending',1,'immediate')
    assert auto.db.claim_one_off(tid)
    assert auto.db.claim_one_off(tid) is None


@pytest.mark.parametrize('terminal',[False,True])
def test_cli_queues_one_off(auto,script,cli,terminal):
    tid=one_off(auto,script,one_off_state='completed' if terminal else 'pending',enabled=not terminal)
    assert cli('run','later')[0]==0
    task=auto.db.get_task(tid)
    assert task['one_off_state']=='pending' and task['enabled']==1
    assert task['one_off_trigger']=='immediate'
    assert task['scheduled_at']<time.time()+1 and task['next_run_at']==task['scheduled_at']


def test_web_create_description_and_script_picker(auto,script):
    once=script('web-one','once',filename='job.py'); repeat=script('repeat')
    assert list_scripts(auto.cfg['scripts_dir'])=={'one_off':[once],'recurring':[repeat]}
    result=auto.client.post('/api/automations/tasks',json={'name':'web-one','description':'用于验证任务说明',
        'script':once,'args':[],'task_kind':'one_off','one_off_trigger':'scheduled','scheduled_at':time.time()+3600})
    assert result.status_code==201
    task=auto.db.get_task_by_name('web-one')
    assert (task['description'],task['task_kind'],task['one_off_state'])==('用于验证任务说明','one_off','pending')
