import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
import tomlkit

spec=importlib.util.spec_from_file_location('migration',Path(__file__).parents[1]/'scripts/migrate/more_agents.py')
migration=importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


@pytest.mark.parametrize('nested',[False,True])
def test_migrate_dry_run_idempotence_and_preservation(tmp_path,capsys,nested):
    root=tmp_path
    config=root/'config'/'acp.toml';config.parent.mkdir()
    config.write_text('# keep comment\ngroups = []\n[[agents]]\nid = "phone"\nname = "Phone"\nhost = "localhost"\nport = 1\ntoken = "secret # verbatim" # token comment\ncwd = "/remote/path"\n')
    old=root/'acp';(old/'items').mkdir(parents=True)
    (old/'sessions.json').write_text(json.dumps({'s':dict(id='s',agent_id='phone',remote_id='r',title='Title')}))
    attachment=dict(id='f',url='/api/acp/uploads/s/f',path=str(old/'uploads'/'s'/'f'))
    items=[dict(id='t',kind='tool',acp_kind='new-unknown',input={'module':'acp'}),dict(id='a',kind='tool',acp_kind='read'),dict(id='u',kind='user',attachments=[attachment]),dict(id='text',kind='text',text='ACP text untouched')]
    (old/'items'/'s.jsonl').write_text(''.join(json.dumps(i)+'\n' for i in items))
    uploads=old/'uploads'/'s';uploads.mkdir(parents=True)
    (uploads/'index.json').write_text(json.dumps({'f':attachment}));(uploads/'f').write_bytes(b'original bytes')
    schedules=root/'builtin'/'schedules.json' if nested else root/'schedules.json'
    parents=root/'agents'/'sessions.json' if nested else root/'sessions.json'
    for p in (schedules,parents): p.parent.mkdir(exist_ok=True)
    schedules.write_text(json.dumps({'job':{'target':dict(module='acp',agent_id='phone',session='new')}}))
    parents.write_text(json.dumps({'sessions':{'child':{'parent':dict(module='acp',session_id='s')}},'uploads':{}}))
    db=root/'workflow'/'app.db';db.parent.mkdir()
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE workflows(id TEXT, name TEXT, definition TEXT)')
        conn.execute('INSERT INTO workflows VALUES(?,?,?)',('wf','Old work',json.dumps({'blocks':[dict(type='builtin.acp_task',params={'agent':'phone','prompt':'hi'})]})))
    before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    migration.migrate(root,True)
    output=capsys.readouterr().out
    assert 's.jsonl' in output and 'sessions.json' in output and 'wf (Old work)' in output and 'fill cwd' in output
    assert before=={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    migration.migrate(root)
    new=root/'more_agents'
    assert not old.exists() and not config.exists()
    raw=(root/'config'/'more_agents.toml').read_text()
    assert '# keep comment' in raw and 'token = "secret # verbatim" # token comment' in raw
    assert tomlkit.parse(raw)['agents'][0]['kind']=='acp'
    assert json.loads((new/'sessions.json').read_text())['s']['cwd']=='/remote/path'
    mapped=[json.loads(line) for line in (new/'items'/'s.jsonl').read_text().splitlines()]
    assert mapped[0]['tool_kind']=='other' and mapped[0]['input']=={'module':'acp'}
    assert mapped[1]['tool_kind']=='read' and 'acp_kind' not in mapped[1]
    assert mapped[2]['attachments'][0]['path']==str(new/'uploads'/'s'/'f')
    assert mapped[3]['phase'] is None
    assert (new/'uploads'/'s'/'f').read_bytes()==b'original bytes'
    assert json.loads((new/'uploads'/'s'/'index.json').read_text())['f']['url']=='/api/more-agents/uploads/s/f'
    assert json.loads(schedules.read_text())['job']['target']['module']=='more_agents'
    assert 'cwd' not in json.loads(schedules.read_text())['job']['target']
    assert json.loads(parents.read_text())['sessions']['child']['parent']['module']=='more_agents'
    with sqlite3.connect(db) as conn: definition=json.loads(conn.execute('SELECT definition FROM workflows').fetchone()[0])
    assert definition['blocks']==[dict(type='builtin.more_agent_task',params={'agent':'phone','prompt':'hi'})]
    after={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    capsys.readouterr();migration.migrate(root)
    assert capsys.readouterr().out==''
    assert after=={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_migration_collision_is_explicit_and_preserves_sources(tmp_path):
    (tmp_path/'acp').mkdir();(tmp_path/'more_agents').mkdir()
    (tmp_path/'acp'/'only-copy').write_text('preserve')
    with pytest.raises(FileExistsError,match='Both'): migration.migrate(tmp_path)
    assert (tmp_path/'acp'/'only-copy').read_text()=='preserve'


def test_core_then_more_agents_migrations(tmp_path):
    config=tmp_path/'config';config.mkdir()
    (config/'acp.toml').write_text('[[agents]]\nid="phone"\nname="Phone"\nhost="localhost"\nport=1\ncwd="/remote/project"\n')
    old=tmp_path/'acp';old.mkdir()
    (old/'sessions.json').write_text(json.dumps({'remote':{'id':'remote','agent_id':'phone'}}))
    (tmp_path/'schedules.json').write_text(json.dumps({'job':{'target':{'module':'acp','agent_id':'phone','session':'new'}}}))
    upload=tmp_path/'uploads'/'child'/'file';upload.parent.mkdir(parents=True);upload.write_bytes(b'upload')
    (tmp_path/'sessions.json').write_text(json.dumps({
        'sessions':{'child':{'id':'child','parent':{'module':'acp','session_id':'remote'}},
                    'unrelated':{'id':'unrelated','parent':{'module':'workflow','run_id':'run'}}},
        'uploads':{'file':{'session_id':'child','path':str(upload)}}}))
    scripts=Path(__file__).parents[1]/'scripts'/'migrate'
    def run(name,*args):
        return subprocess.run([sys.executable,str(scripts/name),'--data',str(tmp_path),*args],
                              check=True,capture_output=True,text=True).stdout
    run('core.py')
    before={str(p.relative_to(tmp_path)):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert 'sessions.json' in run('more_agents.py','--dry-run')
    assert before=={str(p.relative_to(tmp_path)):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    run('more_agents.py')
    index=json.loads((tmp_path/'agents'/'sessions.json').read_text())
    assert index['sessions']['child']['parent']=={'module':'more_agents','session_id':'remote'}
    assert index['sessions']['unrelated']['parent']=={'module':'workflow','run_id':'run'}
    assert index['uploads']['file']['path']==str(tmp_path/'agents'/'uploads'/'child'/'file')
    assert (tmp_path/'agents'/'uploads'/'child'/'file').read_bytes()==b'upload'
    assert json.loads((tmp_path/'builtin'/'schedules.json').read_text())['job']['target']['module']=='more_agents'
    assert json.loads((tmp_path/'more_agents'/'sessions.json').read_text())['remote']['cwd']=='/remote/project'
    assert tomlkit.parse((config/'more_agents.toml').read_text())['agents'][0]['kind']=='acp'
    for path in ('acp','config/acp.toml','sessions.json','schedules.json','uploads'):
        assert not (tmp_path/path).exists()
    after={str(p.relative_to(tmp_path)):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert run('core.py')==run('more_agents.py')==''
    assert after=={str(p.relative_to(tmp_path)):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
