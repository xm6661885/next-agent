import asyncio
import json
import time
from pathlib import Path
from unittest.mock import Mock
import pytest
from server.automations.cli import build_parser

BASE='/api/automations'


def create(auto,script,name='job',**fields):
    response=auto.client.post(BASE+'/tasks',json={'name':name,'script':script(name),**fields})
    assert response.status_code==201,response.text
    return response.json()


def test_next_agent_auth(logged,client,app):
    assert logged.get(BASE+'/tasks').status_code==200
    logged.post('/api/logout')
    assert client.get(BASE+'/settings').status_code==401
    assert 'automations' in app.state.raw_configs


def test_task_crud_status_paging_and_logs(auto,script):
    task=create(auto,script,description='  desc  ',args=['--arg'],schedule_type='interval',schedule_value='60')
    tid=task['id']; path=f'{BASE}/tasks/{tid}'
    assert task['description']=='desc' and task['args_list']==['--arg']
    assert task['next_run_at'] is not None
    assert auto.client.get(BASE+'/tasks/status').json()[str(tid)]['running'] is False
    assert auto.client.get(path+'/status').json()['task_kind']=='recurring'
    updated=auto.client.patch(path,json={'description':'next','args':[]}).json()
    assert updated['next_run_at']==task['next_run_at']
    assert auto.client.post(path+'/disable').json()['next_run_at'] is None
    assert auto.client.post(path+'/enable').json()['enabled']==1
    logfile=auto.root/'history.log'; logfile.write_bytes('first\n中文\n'.encode()+b'\xff\n')
    r1=auto.db.create_run(tid,'manual',str(logfile)); auto.db.finish_run(r1,2)
    r2=auto.db.create_run(tid,'cron','missing.log'); auto.db.finish_run(r2,0)
    assert auto.client.get(path+'/runs?limit=1&offset=1').json()[0]['id']==r1
    assert auto.client.get(BASE+'/runs?limit=1').json()[0]['id']==r2
    tail=auto.client.get(f'{BASE}/runs/{r1}/log').json()
    assert tail['text']=='first\n中文\n�\n' and tail['done']
    assert auto.client.get(f'{BASE}/runs/{r1}/log?offset={tail["offset"]}').json()['text']==''
    assert auto.client.get(f'{BASE}/runs/{r1}/log?offset=-1').status_code==422
    assert auto.client.get(f'{BASE}/runs/{r2}/log').json()['text']==''
    assert auto.client.get(BASE+'/runs/999').status_code==404
    assert auto.client.delete(path).status_code==200
    assert auto.client.get(path).status_code==404
    assert auto.db.list_runs(tid)==[] and logfile.exists()
    assert auto.events[-1]=={'type':'automations_changed','module':'automations'}


@pytest.mark.parametrize('fields',[
    {'name':'..'}, {'name':'x/y'}, {'args':[1]}, {'description':'x'*1001},
    {'schedule_type':'interval','schedule_value':'-1'}, {'schedule_type':'interval','schedule_value':'nan'},
    {'schedule_type':'cron','schedule_value':'invalid'}, {'script':'../outside.sh'},
    {'task_kind':'invalid'}, {'schedule_type':'invalid'},
])
def test_create_validation(auto,script,fields):
    payload={'name':'job','script':script()}; payload.update(fields)
    assert auto.client.post(BASE+'/tasks',json=payload).status_code==422
    assert auto.db.list_tasks()==[]


def test_edit_immutable_fields_and_skeleton(auto):
    response=auto.client.post(BASE+'/tasks',json={'name':'new','create_script':'shell','description':'Hello'})
    assert response.status_code==201,response.text
    task=response.json(); path=auto.scripts/task['script']; assert path.exists()
    assert 'Hello' in path.read_text()
    assert auto.client.post(BASE+'/tasks',json={'name':'new','create_script':'shell'}).status_code==409
    for payload in ({'name':'changed'},{'task_kind':'one_off'},{'args':[1]},{'scheduled_at':time.time()+3600}):
        assert auto.client.patch(f'{BASE}/tasks/{task["id"]}',json=payload).status_code==422
    assert auto.client.get(BASE+'/scripts').json()['recurring']==['cron/new/new.sh']


def test_one_off_actions_and_force(auto,script,monkeypatch):
    rid=Mock(return_value=123); monkeypatch.setattr(auto.manager.scheduler,'_run_claimed_one_off',rid)
    rel=script('once','once')
    response=auto.client.post(BASE+'/tasks',json={'name':'once','script':rel,'task_kind':'one_off',
        'one_off_trigger':'scheduled','scheduled_at':time.time()+3600})
    assert response.status_code==201,response.text
    path=f'{BASE}/tasks/{response.json()["id"]}'
    assert auto.client.post(path+'/run',json={'force':True}).status_code==422
    assert auto.client.post(path+'/start').json()=={'run_id':123}
    assert auto.client.post(path+'/start').status_code==409
    assert auto.client.post(path+'/cancel').status_code==409
    assert auto.client.patch(path,json={'description':'no'}).status_code==422
    auto.db.complete_one_off(response.json()['id'],0)
    assert auto.client.post(path+'/run-again').json()=={'run_id':123}
    assert rid.call_count==2


def test_run_stop_and_enable(auto,script,monkeypatch):
    task=create(auto,script,enabled=False); tid=task['id']; path=f'{BASE}/tasks/{tid}'
    launch=Mock(return_value=10); monkeypatch.setattr(auto.manager.scheduler,'run_now',launch)
    assert auto.client.post(path+'/run').json()=={'run_id':10}
    auto.db.update_task(tid,running_pid=456)
    assert auto.client.post(path+'/run').status_code==409
    assert auto.client.delete(path).status_code==409
    assert auto.client.post(path+'/run',json={'force':True,'extra_args':['--new']}).status_code==200
    assert launch.call_args.args[1]==['--new']
    monkeypatch.setattr(auto.manager.runner,'stop_task',Mock(return_value=True))
    assert auto.client.post(path+'/stop').status_code==200


def test_failures_include_abnormal_and_acknowledgement(auto,script):
    task=create(auto,script); tid=task['id']
    run=auto.db.create_run(tid,'manual','log'); auto.db.finish_run(run,None)
    auto.db.update_task(tid,last_run_at=time.time())
    assert auto.client.get(BASE+'/failures').json()[0]['id']==tid
    assert auto.client.post(BASE+'/failures/acknowledge').status_code==200
    assert auto.client.get(BASE+'/failures').json()==[]
    assert auto.db.get_run(run) is not None


def test_settings_and_raw_config(auto):
    result=auto.client.get(BASE+'/settings').json()
    assert result['webhook_secret'] and result['timezone']
    old=result['webhook_secret']
    fresh=auto.client.post(BASE+'/settings/regenerate').json()
    assert fresh['webhook_secret']!=old and auto.manager.config.data.webhook_secret==fresh['webhook_secret']
    changed=auto.client.patch(BASE+'/settings',json={'scripts_dir':'other/scripts','shell_bin':'tools/bash','poll_interval_sec':3})
    assert changed.status_code==200,changed.text
    assert changed.json()['scripts_dir']==str(auto.root/'other/scripts')
    assert auto.manager.runner.cfg['shell_bin']==str(auto.root/'tools/bash')
    assert auto.manager.scheduler.cfg['poll_interval_sec']==3
    assert auto.client.patch(BASE+'/settings',json={'port':8990}).status_code==422


@pytest.fixture
def webhook(auto,script,monkeypatch):
    task=create(auto,script,schedule_type='webhook')
    auto.cfg['webhook_secret']='secret'
    auto.client.headers.pop('authorization')
    launch=Mock(return_value=99); monkeypatch.setattr(auto.manager.scheduler,'run_webhook',launch)
    return task,launch


@pytest.mark.parametrize('body,status,error',[(b'not-json',400,'request body must be valid JSON'),
    (b'[]',400,'request body must be a JSON object'),(b'"scalar"',400,'request body must be a JSON object'),
    (b'x'*1048577,413,'request body too large')],ids=['invalid-json','array','scalar','too-large'])
def test_webhook_body_contract(auto,webhook,body,status,error):
    response=auto.client.post(BASE+'/webhook/job?secret=secret',content=body)
    assert response.status_code==status and response.json()=={'success':False,'error':error}
    webhook[1].assert_not_called()


def test_webhook_auth_order_and_statuses(auto,webhook):
    task,launch=webhook
    assert auto.client.post(BASE+'/webhook/missing').json()=={'success':False,'error':'task not found'}
    path=BASE+'/webhook/job'
    assert auto.client.post(path,content=b'{}').status_code==401
    response=auto.client.post(path+'?secret=secret',headers={'authorization':'Bearer wrong'},content=b'{}')
    assert response.status_code==401
    response=auto.client.post(path+'?secret=secret',headers={'authorization':'Bearer secret','x-autotask-webhook-secret':'wrong'},content=b'{}')
    assert response.status_code==401
    response=auto.client.post(path,headers={'authorization':'bEaReR secret'},content=b'{ "raw": true }')
    assert response.status_code==202 and response.json()=={'success':True,'run_id':99,'task_name':'job'}
    assert launch.call_args.args[1]==b'{ "raw": true }'
    auto.db.update_task(task['id'],running_pid=123)
    response=auto.client.post(path+'?secret=secret',content=b'{}')
    assert response.status_code==202 and response.json()['skipped']=='task is already running'
    assert launch.call_count==1
    assert auto.client.post(path+'?secret=secret',content=b'[]').status_code==400
    auto.db.update_task(task['id'],enabled=0)
    assert auto.client.post(path).status_code==403
    auto.db.update_task(task['id'],schedule_type='manual')
    assert auto.client.post(path).status_code==409
    assert auto.client.get(path).status_code==405


def test_cli_output_formats(auto,script,cli):
    tid=auto.db.create_task('job',script(),[],'interval','60',description='说明')
    assert cli('list')[1]==f'[{tid:>3}] {"job":<20} {"cron/job/job.sh":<42} {"每60秒":<24} 启用 [未分组] — 说明\n'
    assert json.loads(cli('list','--json')[1])==auto.db.list_tasks()
    assert cli('groups','list')[1]=='暂无分组\n'
    cli('groups','create','工作'); cli('groups','move','job','工作')
    assert cli('groups','list')[1]=='[  1] 工作 (1 个任务)\n'
    assert cli('logs','job')[1]=='暂无运行记录\n'
    log=auto.root/'a.log'; log.write_text('test log\n')
    rid=auto.db.create_run(tid,'manual',str(log)); auto.db.finish_run(rid,3)
    text=cli('logs','job')[1]
    assert text.startswith(f'run#{rid} ') and text.endswith(f'[manual] exit=3  {log}\n')
    assert cli('logs','job','--latest')[1]=='test log\n\n'
    status=cli('status')[1]
    assert f'配置文件: {auto.manager.config.path}\n' in status
    assert f'数据目录: {auto.root}/automations\n' in status
    assert '任务总数: 1（重复/常驻: 1，一次性: 0），运行中: 0\n' in status


def test_cli_public_help_unchanged(capsys):
    parser=build_parser()
    with pytest.raises(SystemExit): parser.parse_args(['_execute-task','--help'])
    text=capsys.readouterr().out
    assert '--extra-args-json EXTRA_ARGS_JSON [--force]' in text
    assert '--run-id' not in text


async def test_poller_detects_cli_and_worker_changes(auto,script,monkeypatch):
    monkeypatch.setattr(auto.manager.scheduler,'start',lambda:None)
    await auto.manager.startup()
    poll=asyncio.create_task(auto.manager.poll())
    try:
        tid=auto.db.create_task('job',script(),[],'manual',None)
        await asyncio.sleep(1.05)
        assert auto.events[-1]=={'type':'automations_changed','module':'automations'}
        auto.events.clear()
        rid=auto.db.create_run(tid,'manual','log'); auto.db.finish_run(rid,0)
        await asyncio.sleep(1.05)
        assert auto.events[-1]['type']=='automations_changed'
    finally:
        poll.cancel()
        with pytest.raises(asyncio.CancelledError): await poll
        await auto.manager.shutdown()


@pytest.mark.parametrize('words', list(json.loads((Path(__file__).with_name('cli_help.json')).read_text())))
def test_cli_help_matches_appendix(words,capsys):
    expected=json.loads((Path(__file__).with_name('cli_help.json')).read_text())[words]
    with pytest.raises(SystemExit) as exc: build_parser().parse_args(words.split())
    assert exc.value.code==0
    assert capsys.readouterr().out==expected
