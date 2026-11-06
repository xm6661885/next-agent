import json
from pathlib import Path
import subprocess
import sys

SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'migrate'/'core.py'


def run(data,*args):
    return subprocess.run([sys.executable,str(SCRIPT),'--data',str(data),*args],check=True,capture_output=True,text=True).stdout


def files(data):
    return {str(p.relative_to(data)):(p.read_bytes(),p.stat().st_mtime_ns) for p in data.rglob('*') if p.is_file()}


def test_migration_dry_run_and_twice(tmp_path):
    data=tmp_path/'data'; data.mkdir()
    (data/'secret.key').write_text('secret')
    (data/'schedules.json').write_text('{"schedule": {}}')
    profile=data/'agents'/'alice'; profile.mkdir(parents=True)
    (profile/'avatar.png').write_bytes(b'avatar')
    (profile/'CLAUDE.md').write_text('instructions')
    fallback=data/'uploads'/'sid'; fallback.mkdir(parents=True)
    (fallback/'file.txt').write_text('upload')
    config=data/'config'; config.mkdir()
    (config/'core.toml').write_text('[server]')
    index={'sessions':{'sid':{'id':'sid'}},'uploads':{
        'fallback':{'session_id':'sid','path':str(fallback/'file.txt')},
        'cwd':{'session_id':'sid','path':str(tmp_path/'project'/'uploads'/'file.txt')},
        'similar':{'session_id':'sid','path':str(data/'uploads-other'/'file.txt')}}}
    original=json.dumps(index)
    (data/'sessions.json').write_text(original)
    before=files(data)
    assert 'Would rewrite 1 upload path(s)' in run(data,'--dry-run')
    assert files(data)==before
    output=run(data)
    assert 'Rewrite 1 upload path(s)' in output
    assert (data/'core'/'secret.key').read_text()=='secret'
    assert (data/'builtin'/'schedules.json').read_text()=='{"schedule": {}}'
    assert (data/'agents'/'profiles'/'alice'/'avatar.png').read_bytes()==b'avatar'
    assert (data/'agents'/'profiles'/'alice'/'CLAUDE.md').read_text()=='instructions'
    assert (data/'agents'/'uploads'/'sid'/'file.txt').read_text()=='upload'
    assert (data/'agents'/'sessions.json.pre-core.bak').read_text()==original
    index['uploads']['fallback']['path']=str(data/'agents'/'uploads'/'sid'/'file.txt')
    assert json.loads((data/'agents'/'sessions.json').read_text())==index
    assert (config/'core.toml').read_text()=='[server]'
    for old in ('secret.key','sessions.json','schedules.json','uploads','agents/alice'):
        assert not (data/old).exists()
    migrated=files(data)
    assert run(data)==''
    assert files(data)==migrated


def test_migration_keeps_existing_destinations(tmp_path):
    pairs=[('secret.key','core/secret.key'),('sessions.json','agents/sessions.json'),
           ('schedules.json','builtin/schedules.json'),('agents/alice/avatar.png','agents/profiles/alice/avatar.png'),
           ('uploads/sid/file.txt','agents/uploads/sid/file.txt')]
    for old,new in pairs:
        for path,content in ((tmp_path/old,'old'),(tmp_path/new,'new')):
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(content)
    index={'uploads':{'f':{'path':str(tmp_path/'uploads'/'sid'/'file.txt')}}}
    (tmp_path/'agents'/'sessions.json').write_text(json.dumps(index))
    before=files(tmp_path)
    assert 'already exists' in run(tmp_path)
    assert files(tmp_path)==before
    run(tmp_path)
    assert files(tmp_path)==before


def test_migration_rewrites_already_moved_index(tmp_path):
    agents=tmp_path/'agents'; agents.mkdir()
    index={'sessions':{},'uploads':{'f':{'path':str(tmp_path/'uploads'/'sid'/'f')}}}
    (agents/'sessions.json').write_text(json.dumps(index))
    run(tmp_path)
    assert json.loads((agents/'sessions.json').read_text())['uploads']['f']['path']==str(agents/'uploads'/'sid'/'f')


def test_migration_profiles_named_like_new_folders(tmp_path):
    for name in ('alice','profiles','uploads'):
        profile=tmp_path/'agents'/name
        profile.mkdir(parents=True)
        (profile/'avatar.png').write_text(name)
        (profile/'CLAUDE.md').write_text(f'Instructions for {name}')
    old_upload=tmp_path/'uploads'/'sid'/'f'
    old_upload.parent.mkdir(parents=True)
    old_upload.write_text('upload')
    before=files(tmp_path)
    assert 'already exists' not in run(tmp_path,'--dry-run')
    assert files(tmp_path)==before
    run(tmp_path)
    for name in ('alice','profiles','uploads'):
        profile=tmp_path/'agents'/'profiles'/name
        assert (profile/'avatar.png').read_text()==name
        assert (profile/'CLAUDE.md').read_text()==f'Instructions for {name}'
    assert (tmp_path/'agents'/'uploads'/'sid'/'f').read_text()=='upload'
    migrated=files(tmp_path)
    run(tmp_path)
    assert files(tmp_path)==migrated


def test_module_paths(app):
    paths=app.state.paths
    assert paths.secret==paths.root/'core'/'secret.key'
    assert paths.sessions==paths.root/'agents'/'sessions.json'
    assert paths.agents==paths.root/'agents'/'profiles'
    assert paths.uploads==paths.root/'agents'/'uploads'
    assert paths.secret.exists() and paths.sessions.exists()
    for directory in (paths.secret.parent,paths.sessions.parent,paths.agents,paths.uploads,paths.config_dir):
        assert directory.is_dir() and directory.stat().st_mode & 0o777==0o700
