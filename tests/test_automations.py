import os
from pathlib import Path
from server.automations.db import DB
from server.automations.scheduler import compute_next_run
from server.automations.runner import Runner


def test_database_schema_and_groups(tmp_path):
    db=DB(str(tmp_path)); tid=db.create_task('test','cron/test/test.sh',[],'manual',None)
    gid=db.create_group('Test'); db.move_task(tid,gid)
    assert db.list_groups()==[{'id':gid,'name':'Test','task_count':1}]
    assert db.delete_group(gid)==1
    assert db.get_task(tid)['group_id'] is None
    assert db._connect().execute('PRAGMA user_version').fetchone()[0]==5


def test_one_off_atomic_claim(tmp_path):
    db=DB(str(tmp_path)); tid=db.create_task('once','once/once/once.sh',[],'once',None,task_kind='one_off',scheduled_at=1,one_off_trigger='scheduled',one_off_state='pending')
    assert db.claim_one_off(tid)
    assert db.claim_one_off(tid) is None
    db.complete_one_off(tid,0)
    assert db.get_task(tid)['one_off_state']=='completed'


def test_interval_due_and_one_off():
    task={'schedule_type':'interval','schedule_value':'10','created_at':10,'last_run_at':None}
    assert compute_next_run(task,now=15)==20
    assert compute_next_run(task,now=25)==25
    assert compute_next_run({'task_kind':'one_off','one_off_state':'pending','enabled':1,'scheduled_at':23},now=15)==23


def test_runner_records_result(tmp_path):
    scripts=tmp_path/'scripts'; scripts.mkdir(); script=scripts/'ok.sh'; script.write_text('echo ok\n')
    db=DB(str(tmp_path)); tid=db.create_task('ok','ok.sh',[],'manual',None); log=tmp_path/'ok.log'; rid=db.create_run(tid,'manual',str(log))
    runner=Runner({'scripts_dir':str(scripts),'shell_bin':'/bin/sh','data_dir':str(tmp_path)},db)
    assert runner.execute_run(db.get_task(tid),rid,str(log),['/bin/sh',str(script)])==0
    assert db.get_run(rid)['exit_code']==0
    assert db.get_task(tid)['running_pid'] is None
    assert 'ok\n' in log.read_text()
