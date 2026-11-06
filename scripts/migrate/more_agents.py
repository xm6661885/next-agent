"""Migrate the former ACP module to More Agents."""
import argparse, json, shutil, sqlite3
from pathlib import Path
import tomlkit

def move(src,dst,dry):
    if not src.exists() or dst.exists(): return False
    if dry: print(f'Move {src} -> {dst}')
    else: dst.parent.mkdir(parents=True,exist_ok=True); shutil.move(str(src),str(dst))
    return True

def migrate_config(root,dry):
    src=root/'config'/'acp.toml'; dst=root/'config'/'more_agents.toml'
    if not src.exists() and not dst.exists(): return
    if dst.exists(): doc=tomlkit.parse(dst.read_text())
    else:
        doc=tomlkit.parse(src.read_text());
        for agent in doc.get('agents',[]): agent['kind']='acp'
        if dry: print(f'Move {src} -> {dst}')
        else: dst.parent.mkdir(parents=True,exist_ok=True); dst.write_text(tomlkit.dumps(doc)); src.unlink()
    if dst.exists() and not dry:
        changed=False
        for agent in doc.get('agents',[]):
            if 'kind' not in agent: agent.insert(1,'kind','acp'); changed=True
        if changed: dst.write_text(tomlkit.dumps(doc))

def migrate_items(root,dry):
    data=root/'more_agents'; path=data/'sessions.json'
    if not path.exists(): return
    sessions=json.loads(path.read_text()); config_path=root/'config'/'more_agents.toml'; agents={}
    if config_path.exists():
        for agent in tomlkit.parse(config_path.read_text()).get('agents',[]): agents[agent['id']]=agent
    changed=False
    for session in sessions.values():
        agent=agents.get(session.get('agent_id'),{}); session.setdefault('kind','acp'); session.setdefault('cwd',agent.get('cwd','/')); changed=True
        item_path=data/'items'/f"{session['id']}.jsonl"
        if item_path.exists():
            lines=[]
            for line in item_path.read_text().splitlines():
                item=json.loads(line)
                if 'acp_kind' in item: item['tool_kind']=item.pop('acp_kind'); changed=True
                lines.append(json.dumps(item,ensure_ascii=False))
            if not dry: item_path.write_text('\n'.join(lines)+'\n')
    if changed and not dry: path.write_text(json.dumps(sessions,ensure_ascii=False,indent=2))

def rewrite(value):
    if isinstance(value,dict):
        for k,v in list(value.items()):
            if k=='module' and v=='acp': value[k]='more_agents'
            else: rewrite(v)
    elif isinstance(value,list):
        for v in value: rewrite(v)

def migrate_json(path,dry):
    if not path.exists(): return
    data=json.loads(path.read_text()); before=json.dumps(data,sort_keys=True); rewrite(data)
    if json.dumps(data,sort_keys=True)!=before:
        print(f'Update {path}') if dry else path.write_text(json.dumps(data,ensure_ascii=False,indent=2))

def migrate_workflow(root,dry):
    db=root/'workflow'/'app.db'
    if not db.exists(): return
    con=sqlite3.connect(db); rows=con.execute("SELECT rowid, definition FROM workflows").fetchall(); updates=[]
    for rowid,raw in rows:
        value=json.loads(raw); changed=False
        def visit(x):
            nonlocal changed
            if isinstance(x,dict):
                if x.get('type')=='builtin.acp_task': x['type']='builtin.more_agent_task'; changed=True
                for v in x.values(): visit(v)
            elif isinstance(x,list):
                for v in x: visit(v)
        visit(value)
        if changed: updates.append((json.dumps(value,ensure_ascii=False),rowid))
    if updates:
        print(f'Update {len(updates)} workflow definitions')
        if not dry: con.executemany('UPDATE workflows SET definition=? WHERE rowid=?',updates); con.commit()
    con.close()

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--data',type=Path,default=Path(__file__).resolve().parents[2]/'data'); parser.add_argument('--dry-run',action='store_true'); args=parser.parse_args(); root=args.data
    migrate_config(root,args.dry_run); move(root/'acp',root/'more_agents',args.dry_run)
    migrate_items(root,args.dry_run); migrate_workflow(root,args.dry_run)
    for path in (root/'schedules.json',root/'builtin'/'schedules.json',root/'sessions.json',root/'agents'/'sessions.json'): migrate_json(path,args.dry_run)

if __name__=='__main__': main()
