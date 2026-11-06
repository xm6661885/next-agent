import importlib.util
import json
from pathlib import Path
import sqlite3

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
    parents.write_text(json.dumps({'child':{'parent':dict(module='acp',session_id='s')}}))
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
    assert json.loads(parents.read_text())['child']['parent']['module']=='more_agents'
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
