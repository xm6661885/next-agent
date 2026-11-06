"""One-off ACP -> More Agents migration. Run with --data DIR [--dry-run]."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import tomlkit

KINDS = {'read','edit','delete','move','search','execute','think','fetch','mcp','other'}

def write(path, text, dry):
    if path.exists() and path.read_text() == text: return
    print(f'Update {path}')
    if dry: return
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as f:
        f.write(text)
    os.replace(f.name, path)


def changed_json(path, value, before, dry):
    if value != before: write(path, json.dumps(value, ensure_ascii=False, indent=2)+'\n', dry)


def move(source, target, dry):
    if not source.exists(): return
    if target.exists(): raise FileExistsError(f'Both {source} and {target} exist; reconcile them before migrating')
    print(f'Move {source} -> {target}')
    if not dry: source.rename(target)


def attachments(value, root):
    if isinstance(value, dict):
        if 'url' in value and isinstance(value['url'], str) and value['url'].startswith('/api/acp/uploads/'):
            value['url'] = value['url'].replace('/api/acp/', '/api/more-agents/', 1)
        if isinstance(value.get('path'), str):
            prefix = str((root/'acp').resolve())+'/'
            if value['path'].startswith(prefix): value['path'] = str((root/'more_agents').resolve())+'/'+value['path'][len(prefix):]
        for child in value.values(): attachments(child, root)
    elif isinstance(value, list):
        for child in value: attachments(child, root)


def migrate(root, dry=False):
    root = root.resolve()
    # Check all collisions before moving either source.
    for source, target in ((root/'config'/'acp.toml',root/'config'/'more_agents.toml'),(root/'acp',root/'more_agents')):
        if source.exists() and target.exists(): raise FileExistsError(f'Both {source} and {target} exist; reconcile them before migrating')
    old_config, config = root/'config'/'acp.toml', root/'config'/'more_agents.toml'
    move(old_config, config, dry)
    read_config = old_config if dry and old_config.exists() else config
    agents = {}
    if read_config.exists():
        doc = tomlkit.parse(read_config.read_text())
        for agent in doc.get('agents', []):
            agent.setdefault('kind','acp')
            agents[agent['id']] = agent
        write(read_config, tomlkit.dumps(doc), dry)
    old_data, data = root/'acp', root/'more_agents'
    move(old_data, data, dry)
    read_data = old_data if dry and old_data.exists() else data
    path = read_data/'sessions.json'
    if path.exists():
        before = json.loads(path.read_text()); sessions = json.loads(path.read_text())
        for session in sessions.values():
            session.setdefault('kind','acp')
            session.setdefault('cwd',agents.get(session['agent_id'],{}).get('cwd','/'))
        changed_json(path,sessions,before,dry)
    for path in sorted((read_data/'items').glob('*.jsonl')):
        raw = path.read_text(); items = [json.loads(line) for line in raw.splitlines() if line]
        before = json.dumps(items,sort_keys=True)
        for item in items:
            if 'acp_kind' in item:
                kind = item.pop('acp_kind');item['tool_kind'] = kind if kind in KINDS else 'other'
            if item['kind']=='text': item.setdefault('phase',None)
            attachments(item.get('attachments',[]),root)
        if json.dumps(items,sort_keys=True)!=before: write(path, ''.join(json.dumps(i,ensure_ascii=False)+'\n' for i in items), dry)
    for path in sorted((read_data/'uploads').glob('*/index.json')):
        before = json.loads(path.read_text()); values = json.loads(path.read_text())
        attachments(values,root)
        changed_json(path,values,before,dry)
    for path in (root/'sessions.json',root/'agents'/'sessions.json'):
        if not path.exists(): continue
        before=json.loads(path.read_text()); values=json.loads(path.read_text())
        for session in values['sessions'].values():
            if (session.get('parent') or {}).get('module')=='acp': session['parent']['module']='more_agents'
        changed_json(path,values,before,dry)
    db=root/'workflow'/'app.db'
    if db.exists():
        con=sqlite3.connect(f'{db.as_uri()}?mode={"ro" if dry else "rw"}',uri=True)
        try:
            for wid, name, raw in con.execute('SELECT id, name, definition FROM workflows').fetchall():
                value=json.loads(raw)
                def visit(value):
                    changed=False
                    if isinstance(value,dict):
                        if value.get('type')=='builtin.acp_task': value['type']='builtin.more_agent_task';changed=True
                        for child in value.values(): changed=visit(child) or changed
                    elif isinstance(value,list):
                        for child in value: changed=visit(child) or changed
                    return changed
                if visit(value):
                    print(f'Workflow {wid} ({name}): rename ACP cards; fill cwd before running new sessions')
                    if not dry: con.execute('UPDATE workflows SET definition=? WHERE id=?',(json.dumps(value,ensure_ascii=False),wid))
            if not dry: con.commit()
        finally: con.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=Path(__file__).resolve().parents[2]/'data')
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    migrate(args.data,args.dry_run)

if __name__=='__main__': main()
