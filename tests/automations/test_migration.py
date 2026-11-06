import importlib.util
import json
import os
import sqlite3
import tomllib
from pathlib import Path
import pytest
from server.automations.db import DB

MODULE=Path(__file__).resolve().parents[2]/'scripts/migrate/automations.py'
spec=importlib.util.spec_from_file_location('automations_migration',MODULE)
migration=importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)


@pytest.fixture
def old(tmp_path):
    source=tmp_path/'old'; data=source/'data'; scripts=source/'scripts'; data.mkdir(parents=True)
    (data/'logs').mkdir(); (data/'logs/a.log').write_text('old log')
    (data/'backups').mkdir(); (data/'backups/history.db').write_bytes(b'historical backup')
    (scripts/'cron/test').mkdir(parents=True); (scripts/'lib').mkdir()
    (scripts/'lib/local_helper.py').write_text('import json\n')
    (scripts/'cron/test/test.py').write_text(f'import os\nimport requests, yaml\nfrom local_helper import f\nROOT={str(source/"scripts")!r}\n')
    (scripts/'cron/test/test.py.bak-old').write_text(str(source/'scripts'))
    (scripts/'cron/test/config.json').write_text(json.dumps({'venv':str(source/'.venv/bin/python'),'db':str(data/'autotask.db')}))
    (scripts/'cron/test/binary').write_bytes(b'\x00'+str(source).encode())
    (scripts/'cron/test/link').symlink_to(source/'scripts/lib/local_helper.py')
    (scripts/'cron/test/.venv').mkdir()
    (scripts/'cron/test/.venv/installed.py').write_text('import excluded_venv_dependency\n')
    (scripts/'cron/test/old.bak-dir').mkdir()
    (scripts/'cron/test/old.bak-dir/old.py').write_text('import excluded_backup_dependency\n')
    (data/'logs/a.log.bak').write_text('backup log')
    (scripts/'cron/test/test.py').chmod(0o750)
    os.utime(scripts/'cron/test/test.py', ns=(1500000000000000000,1500000000000000000))
    site=source/'.venv/lib/python3.13/site-packages'
    for name in ('Flask','PyYAML','croniter','autotask'):
        dist=site/f'{name}-1.0.dist-info'; dist.mkdir(parents=True)
        (dist/'METADATA').write_text(f'Name: {name}\nVersion: 1.0\n')
    (scripts/'cron/test/requirements.txt').write_text('requests\n')
    monitor=scripts/'cron/autotask_failure_monitor/autotask_failure_monitor.py'; monitor.parent.mkdir()
    monitor.write_text('import os\nfrom pathlib import Path\nTASK_DIR = Path(__file__).resolve().parent\nAUTOMATIONS_DIR = TASK_DIR.parents[2]\nDB_PATH = AUTOMATIONS_DIR / "data" / "autotask.db"\n')
    (source/'config.yaml').write_text(f'python_bin: {source}/.venv/bin/python3\nshell_bin: bash\npoll_interval_sec: 2\nwebhook_secret: "abc: \\\"secret\\\""\npassword_hash: discarded\nport: 8990\n')
    db=DB(data)
    tid=db.create_task('test',str(scripts/'cron/test/test.py'),[str(source/'data/logs/a.log')],'manual',None)
    gid=db.create_group('Group'); db.move_task(tid,gid)
    rid=db.create_run(tid,'manual',str(data/'logs/a.log')); db.finish_run(rid,5)
    return source,tmp_path/'new',tid,rid


def snapshot(root):
    return {p.relative_to(root):(p.lstat().st_mode,p.lstat().st_mtime_ns,
            os.readlink(p) if p.is_symlink() else p.read_bytes() if p.is_file() else None)
            for p in [root,*root.rglob('*')]}


def test_dry_run_no_writes_and_idempotent_migration(old,capsys):
    source,data,tid,rid=old
    before=snapshot(source)
    migration.migrate(source,data,True)
    assert not data.exists()
    assert before==snapshot(source)
    migration.migrate(source,data)
    output=capsys.readouterr().out
    assert f'recreate {data}/automations/scripts/cron/test/.venv; requirements: {data}/automations/scripts/cron/test/requirements.txt' in output
    root=data/'automations'; scripts=root/'scripts'; db=DB(root)
    assert before==snapshot(source)
    assert db.get_task(tid)['name']=='test'
    assert db.get_task(tid)['script']==str(scripts/'cron/test/test.py')
    assert json.loads(db.get_task(tid)['args'])==[str(root/'logs/a.log')]
    assert db.get_run(rid)['log_path']==str(root/'logs/a.log')
    assert db.get_run(rid)['exit_code']==5 and db.list_groups()[0]['task_count']==1
    assert not (root/'backups').exists()
    assert not list(root.rglob('*.bak*'))
    assert not list(scripts.rglob('.venv'))
    assert (root/'logs/a.log').read_text()=='old log'
    assert str(source) not in (scripts/'cron/test/test.py').read_text()
    for rel in ('.','cron','cron/test/test.py','cron/test/binary','cron/test','lib'):
        src,dst=source/'scripts'/rel,scripts/rel
        assert src.stat().st_mode==dst.stat().st_mode
        assert src.stat().st_mtime_ns==dst.stat().st_mtime_ns
    assert (scripts/'cron/test/binary').read_bytes()==(source/'scripts/cron/test/binary').read_bytes()
    assert (scripts/'cron/test/link').resolve()==scripts/'lib/local_helper.py'
    monitor=(scripts/'cron/autotask_failure_monitor/autotask_failure_monitor.py').read_text()
    assert 'NEXT_AGENT_DATA' in monitor and 'DB_PATH = DATA_DIR / "automations" / "autotask.db"' in monitor
    config=tomllib.loads((data/'config/automations.toml').read_text())
    assert config['webhook_secret']=='abc: "secret"'
    assert config['python_bin']=='automations/venv/bin/python'
    assert set(config)=={'scripts_dir','python_bin','shell_bin','webhook_secret','poll_interval_sec'}
    assert set((root/'requirements.txt').read_text().splitlines())=={'requests','PyYAML','Flask','croniter'}
    counts=(len(db.list_tasks()),len(db.list_runs()))
    migration.migrate(source,data)
    assert counts==(len(db.list_tasks()),len(db.list_runs()))
    assert tomllib.loads((data/'config/automations.toml').read_text())==config
    assert before==snapshot(source)


def test_conflict_is_detected_before_copying(old):
    source,data,_,_=old
    dest=data/'automations/scripts/cron/test'; dest.mkdir(parents=True)
    (dest/'test.py').write_text('existing file')
    with pytest.raises(ValueError,match='Destination already exists'): migration.migrate(source,data)
    assert (source/'data/autotask.db').exists()
    assert (dest/'test.py').read_text()=='existing file'


def test_sqlite_backup_includes_wal_without_changing_source(old):
    source,data,tid,_=old
    with sqlite3.connect(source/'data/autotask.db') as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('UPDATE tasks SET description=? WHERE id=?',('only in WAL',tid))
        writer.commit()
        assert (source/'data/autotask.db-wal').stat().st_size>0
        before=snapshot(source)
        migration.migrate(source,data)
        assert before==snapshot(source)
        assert DB(data/'automations').get_task(tid)['description']=='only in WAL'
        assert not (data/'automations/autotask.db-shm').exists()
