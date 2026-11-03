"""Reply-scoped MCP connections and cached tool descriptions."""
import hashlib
import json
import re
import time
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.sse import sse_client

_cache = {}


def tool_name(server, tool):
    raw = f'mcp__{server}__{tool}'
    clean = re.sub(r'[^a-zA-Z0-9_-]', '_', raw)
    if clean!=raw or len(clean)>64:
        clean = clean[:51]+'_'+hashlib.sha256(raw.encode()).hexdigest()[:12]
    return clean


@asynccontextmanager
async def tools_for_reply(servers, enabled, notice):
    async with AsyncExitStack() as stack:
        yield SimpleNamespace(servers=servers, enabled=enabled, notice=notice, stack=stack, calls={})


async def list_tools(layer):
    tools = []
    for sid in dict.fromkeys(layer.enabled):
        config = layer.servers.get(sid)
        if config is None:
            layer.notice(f'MCP {sid}: Unknown server')
            continue
        stack = AsyncExitStack()
        try:
            if config.type=='stdio':
                transport = stdio_client(StdioServerParameters(command=config.command, args=config.args, env=config.env or None))
            elif config.type=='http': transport = streamablehttp_client(config.url, headers=config.headers)
            else: transport = sse_client(config.url, headers=config.headers)
            streams = await stack.enter_async_context(transport)
            session = await stack.enter_async_context(ClientSession(*streams[:2], read_timeout_seconds=timedelta(seconds=60)))
            await session.initialize()
            digest = hashlib.sha256(json.dumps(config.model_dump(), sort_keys=True).encode()).hexdigest()
            cached = _cache.get(sid)
            if cached and cached[0]==digest and time.monotonic()-cached[1]<600: listed = cached[2]
            else:
                listed, cursor = [], None
                while True:
                    result = await session.list_tools(cursor=cursor)
                    listed.extend(result.tools)
                    cursor = result.nextCursor
                    if not cursor: break
                _cache[sid] = (digest, time.monotonic(), listed)
            offered = []
            for tool in listed:
                name = tool_name(sid, tool.name)
                if name in layer.calls: raise ValueError('Duplicate tool name')
                offered.append(dict(name=name, description=tool.description or '', parameters=tool.inputSchema))
            for tool, spec in zip(listed, offered): layer.calls[spec['name']] = (session, tool.name)
            tools.extend(offered)
        except BaseException as exc:
            await stack.aclose()
            if not isinstance(exc, Exception): raise
            layer.notice(f'MCP {sid}: {exc}')
        else: layer.stack.push_async_callback(stack.aclose)
    return tools


async def call_tool(layer, name, arguments):
    if name not in layer.calls: return {'content': 'Unknown tool: '+name, 'is_error': True, 'images': []}
    try:
        session, original = layer.calls[name]
        result = await session.call_tool(original, arguments)
        texts, images = [], []
        for block in result.content:
            if block.type=='text': texts.append(block.text)
            elif block.type=='image': images.append(f'data:{block.mimeType};base64,{block.data}')
            else: texts.append(json.dumps(block.model_dump(mode='json'), ensure_ascii=False))
        if result.structuredContent is not None and not texts:
            texts.append(json.dumps(result.structuredContent, ensure_ascii=False))
        return {'content': '\n'.join(texts), 'is_error': bool(result.isError), 'images': images}
    except Exception as exc: return {'content': str(exc), 'is_error': True, 'images': []}
