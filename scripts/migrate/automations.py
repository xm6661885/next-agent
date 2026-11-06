#!/usr/bin/env python3
"""One-off AutoTask cutover. Never run this against the live source service."""
import argparse
import ast
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

import tomlkit
import yaml

REPO = Path(__file__).resolve().parents[2]
DISTRIBUTIONS = {'yaml':'PyYAML', 'PIL':'Pillow', 'bs4':'beautifulsoup4', 'cv2':'opencv-python',
                 'dotenv':'python-dotenv', 'dateutil':'python-dateutil'}


def check_move(source, target):
    if not source.exists() and not source.is_symlink(): return
    if not target.exists() and not target.is_symlink(): return
    if source.is_dir() and target.is_dir() and not source.is_symlink() and not target.is_symlink():
        for child in source.iterdir(): check_move(child, target / child.name)
    else:
        raise ValueError(f'Destination already exists; resolve before cutover: {target}')


def move(source, target):
    if not source.exists() and not source.is_symlink(): return
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir() and target.is_dir() and not source.is_symlink():
        for child in source.iterdir(): move(child, target / child.name)
        source.rmdir()
    else: shutil.move(str(source), str(target))


def tree_files(root):
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            path = Path(directory) / name
            if '.bak' in name: continue
            if path.is_symlink() or path.is_file(): yield path
        dirs[:] = [name for name in dirs if '.bak' not in name]


def mappings(source, data):
    root = data / 'automations'
    result = []
    # Scratch copies still contain the live deployment's absolute paths.
    for old in dict.fromkeys([source, Path('/home/xm666/Automations')]):
        result.extend([(str(old/'config.yaml'), str(data/'config/automations.toml')),
                       (str(old/'scripts'), str(root/'scripts')), (str(old/'data'), str(root)),
                       (str(old/'.venv'), str(root/'venv')), (str(old), str(root))])
    return result


def replace_paths(text, replacements):
    for before, after in replacements: text = text.replace(before, after)
    return text


def rewritten(text, path, replacements, data):
    text = replace_paths(text, replacements)
    if path.name == 'autotask_failure_monitor.py':
        text = text.replace('AUTOMATIONS_DIR = TASK_DIR.parents[2]',
                            f'DATA_DIR = Path(os.environ.get("NEXT_AGENT_DATA", {str(data)!r}))')
        text = text.replace('DB_PATH = AUTOMATIONS_DIR / "data" / "autotask.db"',
                            'DB_PATH = DATA_DIR / "automations" / "autotask.db"')
    return text


def rewrite_tree(root, replacements, data, dry_run):
    # Preserve the original file by moving it to a skipped backup before replacing.
    # Generated binary/browser files are moved unchanged, never decoded or executed.
    for path in tree_files(root):
        if path.is_symlink():
            old = os.readlink(path); new = replace_paths(old, replacements)
            if old != new:
                print(f'Retarget symlink: {path}')
                if not dry_run:
                    backup = path.with_name(path.name+'.bak-automations')
                    if backup.exists() or backup.is_symlink(): raise ValueError(f'Backup exists: {backup}')
                    path.rename(backup); path.symlink_to(new)
            continue
        with path.open('rb') as stream:
            if b'\0' in stream.read(8192): continue
        try: text = path.read_text(encoding='utf-8')
        except UnicodeDecodeError: continue
        new = rewritten(text, path, replacements, data)
        if text == new: continue
        print(f'Rewrite: {path}')
        if not dry_run:
            backup = path.with_name(path.name+'.bak-automations')
            if backup.exists(): raise ValueError(f'Backup exists: {backup}')
            mode = path.stat().st_mode
            path.rename(backup)
            path.write_text(new, encoding='utf-8'); path.chmod(mode)


def inventory(root):
    scripts = [p for p in tree_files(root) if p.suffix == '.py' and not p.is_symlink()
               and not any(x.startswith('.') or x in ('browser-profile','__pycache__','site-packages')
                           for x in p.relative_to(root).parts)]
    local = {p.stem for p in scripts} | {p.parent.name for p in scripts if p.name == '__init__.py'}
    imports = {}
    for path in scripts:
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): names = [item.name.split('.')[0] for item in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0: names = [node.module.split('.')[0]]
            else: continue
            for name in names:
                if name in sys.stdlib_module_names or name in local: continue
                imports.setdefault(name, set()).add(path.relative_to(root).as_posix())
    return {name: {'distribution':DISTRIBUTIONS.get(name,name), 'files':sorted(files)}
            for name,files in sorted(imports.items())}


def migrate(source, data, dry_run=False):
    source, data = Path(source).resolve(), Path(data).resolve()
    if data == source or data.is_relative_to(source): raise ValueError('Destination must be outside the source tree')
    root = data/'automations'
    source_db = source/'data/autotask.db'
    if not source_db.exists() and not (root/'autotask.db').exists(): raise ValueError('AutoTask database not found')
    replacements = mappings(source, data)
    moves = [(source/'data'/name, root/name) for name in ('autotask.db','autotask.db-wal','autotask.db-shm','logs','backups')]
    moves.append((source/'scripts', root/'scripts'))
    for src,dst in moves: check_move(src,dst)
    scripts = source/'scripts' if (source/'scripts').exists() else root/'scripts'
    imports = inventory(scripts)
    per_task_venvs = [p.relative_to(scripts) for p in scripts.glob('*/*/.venv') if p.is_dir()]
    config_path = data/'config/automations.toml'
    config = None
    if not config_path.exists():
        old = yaml.safe_load((source/'config.yaml').read_text())
        config = dict(scripts_dir='automations/scripts', python_bin='automations/venv/bin/python',
                      shell_bin=old.get('shell_bin','/bin/bash'), poll_interval_sec=old.get('poll_interval_sec',2),
                      webhook_secret=old.get('webhook_secret',''))
        # Resolve the old shell command now; new relative config paths are data-root relative.
        if not os.path.isabs(config['shell_bin']):
            config['shell_bin'] = shutil.which(config['shell_bin'])
            if not config['shell_bin']: raise ValueError('Configured shell is not on PATH')
        python = old.get('python_bin','')
        if python and not any(python.startswith(str(old/'.venv')) for old in (source,Path('/home/xm666/Automations'))):
            config['python_bin'] = replace_paths(python,replacements) if os.path.isabs(python) else shutil.which(python)
            if not config['python_bin']: raise ValueError('Configured Python is not on PATH')
    for src,dst in moves:
        if src.exists() or src.is_symlink():
            print(f'{"Would move" if dry_run else "Move"}: {src} -> {dst}')
            if not dry_run: move(src,dst)
    if not dry_run: scripts = root/'scripts'
    rewrite_tree(scripts,replacements,data,dry_run)
    print('Rewrite stored absolute log paths (and absolute entry paths/arguments) without changing IDs or history')
    if not dry_run:
        with sqlite3.connect(root/'autotask.db') as conn:
            for row in conn.execute('SELECT id, log_path FROM runs WHERE log_path IS NOT NULL').fetchall():
                new = replace_paths(row[1],replacements)
                if new != row[1]: conn.execute('UPDATE runs SET log_path = ? WHERE id = ?', (new,row[0]))
            for tid,script,args in conn.execute('SELECT id, script, args FROM tasks').fetchall():
                new_script = replace_paths(script,replacements)
                new_args = json.dumps([replace_paths(arg,replacements) for arg in json.loads(args)],ensure_ascii=False)
                if new_script != script or json.loads(new_args) != json.loads(args):
                    conn.execute('UPDATE tasks SET script = ?, args = ? WHERE id = ?', (new_script,new_args,tid))
    if config is not None:
        print(f'{"Would write" if dry_run else "Write"}: {config_path} (secret preserved)')
        if not dry_run:
            config_path.parent.mkdir(parents=True,exist_ok=True)
            config_path.write_text(tomlkit.dumps(config)); config_path.chmod(0o600)
    print('Write third-party import inventory and requirements.txt:', ', '.join(imports) or '(none)')
    if not dry_run:
        (root/'requirements.txt').write_text(''.join(name+'\n' for name in sorted({v['distribution'] for v in imports.values()})))
        (root/'imports.json').write_text(json.dumps(imports,ensure_ascii=False,indent=2)+'\n')
        for name in ('logs','tmp','scripts/cron','scripts/once','scripts/lib'): (root/name).mkdir(parents=True,exist_ok=True)
    print(f'Follow-up: create {root}/venv; review imports.json and install requirements.txt with uv pip.')
    for path in per_task_venvs:
        dest = root/'scripts'/path
        print(f'Follow-up: move {dest} to a backup; recreate it and install {dest.parent}/requirements.txt.')
    print('Follow-up: verify no old source paths remain outside *.bak*; archive/delete skipped backups after verification.')
    print('Follow-up: install scripts/autotask to ~/.local/bin/autotask; retire autotaskd; start next-agent; update webhook senders.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='/home/xm666/Automations', type=Path)
    parser.add_argument('--data', default=REPO/'data', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    migrate(args.source,args.data,args.dry_run)


if __name__ == '__main__': main()
