"""Move core and Claude Agents data into their module folders (run before startup)."""
import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile


def migrate(data, dry_run=False):
    data=Path(data).expanduser().resolve()
    agents=data/'agents'
    moved=set()

    def move(source, target):
        if not source.exists(): return
        if target.exists() and target not in moved:
            print(f'Skip {source}: {target} already exists')
            return
        print(f'{"Would move" if dry_run else "Move"} {source} -> {target}')
        if not dry_run:
            target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            source.rename(target)
        moved.add(source)

    move(data/'secret.key',data/'core'/'secret.key')
    move(data/'sessions.json',agents/'sessions.json')
    if agents.exists():
        profiles=[]
        for profile in sorted(agents.iterdir()):
            if not profile.is_dir(): continue
            if profile.name in ('profiles','uploads') and not (
                    any(profile.glob('avatar.*')) or (profile/'CLAUDE.md').exists()): continue
            target=agents/'profiles'/profile.name
            # An old agent named "profiles" already occupies the new profile container.
            if profile.name=='profiles': profiles.extend((child,target/child.name) for child in profile.iterdir())
            else: profiles.append((profile,target))
        for source,target in profiles: move(source,target)
    move(data/'uploads',agents/'uploads')
    move(data/'schedules.json',data/'builtin'/'schedules.json')

    sessions=agents/'sessions.json'
    source=sessions if sessions.exists() else data/'sessions.json'
    if not source.exists(): return
    # A destination collision leaves the old uploads in place, so keep their paths too.
    if (data/'uploads').exists() and data/'uploads' not in moved: return
    index=json.loads(source.read_text())
    prefix=str(data/'uploads')+'/'
    count=0
    for upload in index.get('uploads',{}).values():
        if upload['path'].startswith(prefix):
            upload['path']=str(agents/'uploads')+'/'+upload['path'][len(prefix):]
            count+=1
    if not count: return
    print(f'{"Would rewrite" if dry_run else "Rewrite"} {count} upload path(s) in {sessions}')
    backup=sessions.with_suffix('.json.pre-core.bak')
    if not backup.exists():
        print(f'{"Would back up" if dry_run else "Back up"} {sessions} -> {backup}')
        if not dry_run: shutil.copy2(sessions,backup)
    if not dry_run:
        with tempfile.NamedTemporaryFile(mode='w',dir=sessions.parent,delete=False) as stream:
            temp=Path(stream.name)
            json.dump(index,stream,indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(sessions)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=Path(__file__).resolve().parents[2]/'data')
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    migrate(args.data,args.dry_run)


if __name__=='__main__': main()
