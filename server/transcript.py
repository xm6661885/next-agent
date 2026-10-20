"""Read CLI transcripts (~/.claude/projects/<project>/<session>.jsonl) without SDK internals.

Layout follows the CLI: the project dir name is the realpath with every non-alphanumeric
character replaced by '-'; names over 200 chars are truncated and get a hash suffix,
which differs between CLI builds, so long names are matched by prefix."""
import json
import os
import unicodedata
import re
from dataclasses import dataclass
from pathlib import Path

MAX_NAME = 200
ENTRY_TYPES = {'user','assistant','progress','system','attachment'}
_NON_ALNUM = re.compile(r'[^a-zA-Z0-9]')

@dataclass
class Message:
    type: str
    uuid: str
    message: dict | None
    parent_tool_use_id: str | None = None
    compact_summary: bool = False

def projects_dir():
    base = os.environ.get('CLAUDE_CONFIG_DIR') or str(Path.home()/'.claude')
    return Path(unicodedata.normalize('NFC',base))/'projects'

def project_dir(cwd):
    try: path = os.path.realpath(cwd)
    except OSError: path = cwd
    name = _NON_ALNUM.sub('-',unicodedata.normalize('NFC',path))
    root = projects_dir()
    if len(name) <= MAX_NAME:
        return root/name if (root/name).is_dir() else None
    try:
        return next((p for p in root.iterdir() if p.is_dir() and p.name.startswith(name[:MAX_NAME]+'-')),None)
    except OSError:
        return None

def transcript_path(sdk_id, cwd):
    project = project_dir(cwd)
    return project/f'{sdk_id}.jsonl' if project else None

def read_entries(path):
    """Transcript entries with a uuid; corrupt lines are skipped."""
    out = []
    try: stream = open(path,encoding='utf-8',errors='replace')
    except OSError: return out
    with stream:
        for line in stream:
            line = line.strip()
            if not line: continue
            try: entry = json.loads(line)
            except ValueError: continue
            if isinstance(entry,dict) and entry.get('type') in ENTRY_TYPES and isinstance(entry.get('uuid'),str):
                out.append(entry)
    return out

def _parent(entry):
    # compact_boundary has parentUuid null; logicalParentUuid keeps the pre-compaction history attached.
    return entry.get('parentUuid') or (entry.get('logicalParentUuid') if entry.get('subtype')=='compact_boundary' else None)

def main_chain(entries):
    """Walk back from the newest main-thread user/assistant leaf to the root."""
    by_uuid = {e['uuid']:e for e in entries}
    order = {e['uuid']:i for i,e in enumerate(entries)}
    parents = {p for e in entries if (p := _parent(e))}
    leaves = []
    for terminal in (e for e in entries if e['uuid'] not in parents):
        cur, seen = terminal, set()
        while cur and cur['uuid'] not in seen:
            seen.add(cur['uuid'])
            if cur.get('type') in ('user','assistant'):
                leaves.append(cur); break
            cur = by_uuid.get(_parent(cur))
    if not leaves: return []
    main = [l for l in leaves if not (l.get('isSidechain') or l.get('teamName') or l.get('isMeta'))] or leaves
    cur = max(main,key=lambda e:order[e['uuid']])
    chain, seen = [], set()
    while cur and cur['uuid'] not in seen:
        seen.add(cur['uuid']); chain.append(cur)
        cur = by_uuid.get(_parent(cur))
    chain.reverse()
    return chain

def _visible(entry):
    return entry.get('type') in ('user','assistant') and not (entry.get('isMeta') or entry.get('isSidechain') or entry.get('teamName'))

def _message(entry, parent=None):
    return Message(entry['type'],entry['uuid'],entry.get('message'),parent,bool(entry.get('isCompactSummary')))

def session_messages(sdk_id, cwd):
    path = transcript_path(sdk_id,cwd)
    if not path: return []
    return [_message(e) for e in main_chain(read_entries(path)) if _visible(e)]

def subagent_path(sdk_id, cwd, aid):
    project = project_dir(cwd)
    if not project: return None
    base = project/sdk_id/'subagents'
    direct = base/f'agent-{aid}.jsonl'
    if direct.exists(): return direct
    # Nested layouts (subagents/<group>/agent-<id>.jsonl) exist in newer CLIs.
    return next(iter(base.rglob(f'agent-{aid}.jsonl')),None) if base.is_dir() else None

def subagent_messages(sdk_id, cwd, aid):
    path = subagent_path(sdk_id,cwd,aid)
    if not path: return []
    parent = None
    try:
        meta = json.loads(path.with_name(path.name[:-len('.jsonl')]+'.meta.json').read_text(encoding='utf-8'))
        if isinstance(meta,dict) and isinstance(meta.get('toolUseId'),str): parent = meta['toolUseId']
    except (OSError,ValueError):
        pass
    return [_message(e,parent) for e in main_chain(read_entries(path)) if e.get('type') in ('user','assistant')]
