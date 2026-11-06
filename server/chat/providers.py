"""Provider HTTP requests, SSE normalization and transcript conversion."""
import base64
from html import escape
import json
from pathlib import Path
import httpx


class ProviderError(Exception):
    pass


def client():
    return httpx.AsyncClient(trust_env=True, timeout=httpx.Timeout(60, read=300))


def headers(provider):
    auth = {'Authorization': 'Bearer '+provider.api_key} if provider.format=='openai' else {
        'x-api-key': provider.api_key, 'anthropic-version': '2023-06-01'}
    return {**auth, **provider.headers}


def url(provider, endpoint):
    return provider.base_url.rstrip('/')+'/'+endpoint


async def check(response):
    if response.is_error:
        body = (await response.aread()).decode(errors='replace')[:1000]
        raise ProviderError(f'{response.status_code}: {body}')


async def sse(response):
    data = []
    async for line in response.aiter_lines():
        if line.startswith('data:'): data.append(line[5:].lstrip(' '))
        elif not line and data:
            raw, data = '\n'.join(data), []
            if raw=='[DONE]': return
            value = json.loads(raw)
            if not isinstance(value, dict): raise ProviderError('Invalid SSE response')
            if value.get('error'): raise ProviderError(json.dumps(value['error'], ensure_ascii=False)[:1000])
            yield value
    if data:
        raw = '\n'.join(data)
        if raw!='[DONE]':
            value = json.loads(raw)
            if not isinstance(value, dict): raise ProviderError('Invalid SSE response')
            if value.get('error'): raise ProviderError(json.dumps(value['error'], ensure_ascii=False)[:1000])
            yield value


def history(items, format):
    messages, assistant, results = [], [], []

    def append(role, content, **extra):
        if format=='anthropic' and messages and messages[-1]['role']==role:
            messages[-1]['content'].extend(content)
        else: messages.append(dict(role=role, content=content, **extra))

    def flush():
        if assistant:
            if format=='anthropic': append('assistant', list(assistant))
            else:
                text = ''.join(b['text'] for b in assistant if b['type']=='text')
                calls = [dict(id=b['id'], type='function', function={'name': b['name'], 'arguments': json.dumps(b['input'])})
                         for b in assistant if b['type']=='tool_use']
                append('assistant', text or None, **({'tool_calls': calls} if calls else {}))
        if results:
            if format=='anthropic': append('user', list(results))
            else:
                for r in results: append('tool', r['content'], tool_call_id=r['tool_use_id'])
        assistant.clear()
        results.clear()

    for item in items:
        kind = item['kind']
        if kind=='user':
            flush()
            blocks = [{'type': 'text', 'text': item['text']}] if item['text'] else []
            for a in item.get('attachments', []):
                if a.get('is_text'):
                    text = Path(a['path']).read_bytes().decode('utf-8')
                    content = text[:50000]
                    if len(text)>50000: content += '\nThe rest of this file can be read with file_read.'
                    blocks.append({'type': 'text', 'text': f'<file name="{escape(a["name"], quote=True)}">\n{content}\n</file>'})
                    continue
                data = base64.b64encode(Path(a['path']).read_bytes()).decode()
                if format=='openai': blocks.append({'type': 'image_url', 'image_url': {'url': f"data:{a['mime']};base64,{data}"}})
                else: blocks.append({'type': 'image', 'source': {'type': 'base64', 'media_type': a['mime'], 'data': data}})
            append('user', blocks)
        elif kind=='text' and item['text']:
            if results: flush()
            assistant.append({'type': 'text', 'text': item['text']})
        elif kind=='tool':
            result = item.get('result') or {'content': 'Tool call interrupted', 'is_error': True}
            assistant.append({'type': 'tool_use', 'id': item['tool_use_id'], 'name': item['name'], 'input': item['input']})
            results.append({'type': 'tool_result', 'tool_use_id': item['tool_use_id'],
                            'content': result['content'], 'is_error': result['is_error']})
        elif kind=='result': flush()
    flush()
    return messages


def payload(provider, model, messages, system, tools, effort, temperature, max_tokens):
    body = {'model': model, 'messages': messages, 'stream': True}
    if temperature>=0: body['temperature'] = temperature
    if provider.format=='openai':
        if system: body['messages'] = [{'role': 'system', 'content': system}, *messages]
        if effort and effort!='off': body['reasoning_effort'] = 'high' if effort=='max' else effort
        if max_tokens: body['max_tokens'] = max_tokens
        if tools: body['tools'] = [{'type': 'function', 'function': t} for t in tools]
        body['stream_options'] = {'include_usage': True}
    else:
        if system: body['system'] = system
        body['max_tokens'] = max_tokens or 8192
        if effort and effort!='off':
            budget = {'low': 2048, 'medium': 8192, 'high': 16384, 'max': 32000}[effort]
            body['thinking'] = {'type': 'enabled', 'budget_tokens': budget}
            body['max_tokens'] = max(body['max_tokens'], budget+8192)
            body.pop('temperature', None)  # Extended thinking requires the provider's default temperature.
        if tools: body['tools'] = [dict(name=t['name'], description=t.get('description', ''), input_schema=t['parameters']) for t in tools]
    return body


async def openai(provider, body):
    calls, reason = {}, None
    async with client() as http:
        async with http.stream('POST', url(provider, 'chat/completions'), headers=headers(provider), json=body) as response:
            await check(response)
            async for chunk in sse(response):
                usage = chunk.get('usage')
                if usage:
                    yield {'type': 'usage', 'input': usage.get('prompt_tokens', 0), 'output': usage.get('completion_tokens', 0)}
                choices = chunk.get('choices') or []
                if not choices: continue
                choice = choices[0]
                delta = choice.get('delta') or {}
                for field, kind in (('reasoning_content', 'thinking'), ('reasoning', 'thinking'), ('content', 'text')):
                    if delta.get(field): yield {'type': kind, 'text': delta[field]}
                for call in delta.get('tool_calls') or []:
                    index = call['index']
                    function = call.get('function') or {}
                    if index not in calls:
                        if not call.get('id') or not function.get('name'): raise ProviderError('Invalid tool call')
                        calls[index] = call['id']
                        yield {'type': 'tool_start', 'id': call['id'], 'name': function['name'], 'input': {}}
                    if function.get('arguments'):
                        yield {'type': 'tool_args', 'id': calls[index], 'text': function['arguments']}
                if choice.get('finish_reason'): reason = choice['finish_reason']
    if reason is None: raise ProviderError('Provider stream ended without a stop reason')
    for tid in calls.values(): yield {'type': 'tool_end', 'id': tid}
    yield {'type': 'stop', 'reason': reason}


async def anthropic(provider, body):
    calls, reason, stopped = {}, None, False
    async with client() as http:
        async with http.stream('POST', url(provider, 'messages'), headers=headers(provider), json=body) as response:
            await check(response)
            async for chunk in sse(response):
                kind = chunk.get('type')
                if kind=='message_start':
                    usage = chunk['message'].get('usage', {})
                    yield {'type': 'usage', 'input': usage.get('input_tokens', 0), 'output': usage.get('output_tokens', 0)}
                elif kind=='content_block_start':
                    block = chunk['content_block']
                    if block['type']=='tool_use':
                        calls[chunk['index']] = block['id']
                        yield {'type': 'tool_start', 'id': block['id'], 'name': block['name'], 'input': block.get('input', {})}
                    elif block['type'] in ('text', 'thinking') and block.get(block['type']):
                        yield {'type': block['type'], 'text': block[block['type']]}
                elif kind=='content_block_delta':
                    delta = chunk['delta']
                    if delta['type']=='text_delta': yield {'type': 'text', 'text': delta['text']}
                    elif delta['type']=='thinking_delta': yield {'type': 'thinking', 'text': delta['thinking']}
                    elif delta['type']=='input_json_delta':
                        yield {'type': 'tool_args', 'id': calls[chunk['index']], 'text': delta['partial_json']}
                elif kind=='content_block_stop':
                    if chunk['index'] in calls: yield {'type': 'tool_end', 'id': calls[chunk['index']]}
                    else: yield {'type': 'block_end'}
                elif kind=='message_delta':
                    reason = chunk['delta'].get('stop_reason') or reason
                    usage = chunk.get('usage', {})
                    yield {'type': 'usage', **{k: usage[v] for k, v in (('input', 'input_tokens'), ('output', 'output_tokens')) if v in usage}}
                elif kind=='message_stop': stopped = True
    if not stopped or reason is None: raise ProviderError('Provider stream ended without a stop reason')
    yield {'type': 'stop', 'reason': reason}


async def stream(provider, model, messages, system, tools, effort, temperature, max_tokens):
    body = payload(provider, model, messages, system, tools, effort, temperature, max_tokens)
    handler = openai if provider.format=='openai' else anthropic
    async for event in handler(provider, body): yield event


async def complete(provider, model, messages, system='', max_tokens=64):
    body = payload(provider, model, messages, system, [], 'off', -1, max_tokens)
    body['stream'] = False
    body.pop('stream_options', None)
    async with client() as http:
        response = await http.post(url(provider, 'chat/completions' if provider.format=='openai' else 'messages'),
                                   headers=headers(provider), json=body)
        await check(response)
        data = response.json()
    if provider.format=='openai': return data['choices'][0]['message']['content']
    return ''.join(b['text'] for b in data['content'] if b['type']=='text')


async def list_models(provider) -> list[str]:
    async with client() as http:
        response = await http.get(url(provider, 'models'), headers=headers(provider))
        await check(response)
        try: data = response.json()
        except ValueError as exc: raise ProviderError('Invalid models response') from exc
    entries = data.get('data') if isinstance(data, dict) else None
    if not isinstance(entries, list) or any(not isinstance(m, dict) or not isinstance(m.get('id'), str) for m in entries):
        raise ProviderError('Invalid models response')
    return sorted({m['id'] for m in entries})


async def test(provider):
    try:
        if provider.format=='openai':
            return {'ok': True, 'models': await list_models(provider)}
        if not provider.models: raise ProviderError('No models configured')
        await complete(provider, provider.models[0], [{'role': 'user', 'content': 'Hi'}], max_tokens=1)
        return {'ok': True}
    except Exception as exc: return {'ok': False, 'error': str(exc)}
