"""Read and search only the calling agent's history."""
import json
from pydantic import Field
from . import Input, epoch, mcp_tool


class ListHistory(Input):
    limit: int = Field(default=20, ge=1, le=200)
    before: float | None = Field(default=None, allow_inf_nan=False)


class SearchHistory(Input):
    query: str = Field(min_length=1)
    limit: int = Field(default=20, ge=1, le=200)


class ReadHistory(Input):
    session_id: str = Field(min_length=1)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=40, ge=1, le=200)


def flatten(items):
    out = []
    for item in items:
        kind = item['kind']
        if kind in ('user', 'text'):
            out.append({'role': 'user' if kind=='user' else 'assistant', 'text': item['text'][:4000]})
        elif kind=='tool':
            summary = ' '.join(json.dumps(item['input'], ensure_ascii=False).split())[:500]
            out.append({'role': 'tool', 'text': item['name']+': '+summary})
    return out


def history_tools(builtin, caller):
    def own():
        return sorted((s for s in builtin.sessions('agents') if s['agent_id']==caller['agent_id']),
                      key=lambda s: s['updated_at'], reverse=True)

    async def listing(args):
        return [dict(session_id=s['id'], title=s['title'], preview=s['preview'], updated_at=s['updated_at'],
                     origin=s.get('origin', 'ui')) for s in own() if s['id']!=caller['session_id']
                and (args.before is None or epoch(s['updated_at'])<args.before)][:args.limit]

    async def search(args):
        hits = await builtin.agents.search(caller['agent_id'], args.query, args.limit)
        return [dict(session_id=h['session']['id'], title=h['session']['title'], snippet=h['snippet'],
                     updated_at=h['session']['updated_at']) for h in hits]

    async def read(args):
        session = next((s for s in own() if s['id']==args.session_id), None)
        if session is None: raise ValueError('Session does not belong to this agent')
        items = flatten(builtin.core.bridge.items('agents', args.session_id))
        return dict(title=session['title'], total=len(items), items=items[args.offset:args.offset+args.limit])

    return [mcp_tool('history_list', 'List this agent\'s other sessions, newest first.', ListHistory, listing),
            mcp_tool('history_search', 'Search this agent\'s session titles and conversation text.', SearchHistory, search),
            mcp_tool('history_read', 'Read text and tool calls from a session of this agent.', ReadHistory, read)]
