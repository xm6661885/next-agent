import asyncio
import importlib.util
import json
from pathlib import Path
import tomlkit
import pytest
from server.chat import providers
from server.chat.local_tools import LocalTools
from server.chat.routes import ConfigPatch
from server.chat.resources import Resources
from test_chat import chat, until


async def upload(c, path, text='One\nTwo\nTHREE', name='notes.txt'):
    response = await c.post(path, files={'files': (name, text.encode(), 'text/plain')})
    assert response.status_code==200, response.text
    return response.json()[0]


async def test_title_background_and_manual_rename(chat, monkeypatch):
    m = chat.manager
    entered, release = asyncio.Event(), asyncio.Event()
    requests = []

    async def complete(provider, model, messages, system):
        requests.append((model, messages, system))
        entered.set()
        await release.wait()
        return ' " A  better\n title " '

    monkeypatch.setattr(providers, 'complete', complete)
    m.patch_config(ConfigPatch(titles={'model': 'local/large', 'prompt': 'Custom title prompt'}))
    runtime = m.runtime(m.create_session('_default')['id'])
    runtime.send('  First   sentence。Second sentence!')
    assert runtime.session['title']=='First sentence'
    assert any(e['type']=='session' and e['session']['title']=='First sentence' for e in runtime.ring)
    await entered.wait()
    await runtime.task
    assert not runtime.title_task.done() and runtime.state=='idle'
    assert runtime.session['usage']=={'input': 22, 'output': 10}
    m.update_session(runtime.sid, title='Manual rename')
    release.set()
    await runtime.title_task
    assert runtime.session['title']=='Manual rename'
    assert requests==[('large', [{'role': 'user', 'content': '  First   sentence。Second sentence!'}], 'Custom title prompt')]


@pytest.mark.parametrize('generated', [' "New   title" ', '', ' "" ', RuntimeError('Unavailable'), '字'*40])
async def test_title_success_empty_failure_and_default_prompt(chat, monkeypatch, generated):
    m = chat.manager

    async def complete(provider, model, messages, system):
        assert model=='small'
        assert system=='Write only a short title for this conversation, at most 30 characters, in the language of the message.'
        if isinstance(generated, Exception): raise generated
        return generated

    monkeypatch.setattr(providers, 'complete', complete)
    runtime = m.runtime(m.create_session('_default')['id'])
    runtime.send('Fallback? Rest')
    assert runtime.session['title']=='Fallback'
    await runtime.title_task
    expected = 'New title' if generated==' "New   title" ' else '字'*30 if generated=='字'*40 else 'Fallback'
    assert runtime.session['title']==expected
    await runtime.task


@pytest.mark.parametrize('text, expected', [('a'*80+'! rest', 'a'*60), ('Hello\nWorld', 'Hello'),
                                         ('hello. rest', 'hello'), ('   ', 'first.txt')])
async def test_title_disabled_sentence_and_attachment(chat, text, expected):
    m = chat.manager
    m.patch_config(ConfigPatch(titles={'enabled': False}))
    runtime = m.runtime(m.create_session('_default')['id'])
    attachment = await upload(chat.http, f'/api/chat/sessions/{runtime.sid}/uploads', name='first.txt')
    runtime.send(text, [attachment])
    assert runtime.session['title']==expected and runtime.title_task is None
    await runtime.task
    assert all(body.get('stream') for _, body in chat.peer.requests)


@pytest.mark.parametrize('close', ['delete', 'shutdown'])
async def test_title_task_cancelled_with_session(chat, monkeypatch, close):
    m = chat.manager
    entered = asyncio.Event()

    async def complete(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(providers, 'complete', complete)
    runtime = m.runtime(m.create_session('_default')['id'])
    runtime.send('hello')
    await entered.wait()
    await runtime.task
    if close=='delete': await m.delete_session(runtime.sid)
    else: await m.close()
    assert runtime.title_task.cancelled()


async def test_assistant_file_crud_validation_and_isolation(chat):
    m, c = chat.manager, chat.http
    aid = m.create_assistant({'name': 'Files'})['id']
    path = f'/api/chat/assistants/{aid}/files'
    record = await upload(c, path, text='你好\nsecond\n', name='中文.txt')
    assert set(record)=={'id', 'name', 'size', 'chars', 'lines', 'created_at'}
    assert record['name']=='中文.txt' and record['size']==14 and record['chars']==10 and record['lines']==2
    assert (await c.get(path)).json()==[record]
    download = await c.get(path+'/'+record['id'])
    assert download.text=='你好\nsecond\n' and download.headers['content-type'].startswith('text/plain')
    renamed = await c.patch(path+'/'+record['id'], json={'name': 'renamed.txt'})
    assert renamed.json()['name']=='renamed.txt'
    assert (await c.patch(path+'/'+record['id'], json={'name': ''})).status_code==422
    assert (await c.get('/api/chat/assistants/_default/files')).json()==[]
    assert (await c.get('/api/chat/assistants/_default/files/'+record['id'])).status_code==404
    for content in (b'bad\xff', b'nul\x00text'):
        assert (await c.post(path, files={'files': ('x', content)})).status_code==415
    assert (await c.post(path, files={'files': ('x', b'x'*(2*1024*1024+1))})).status_code==413
    assert (await c.get('/api/chat/assistants/missing/files')).status_code==404
    assert (await c.delete(path+'/'+record['id'])).json()=={'ok': True}
    assert (await c.get(path)).json()==[]
    assert (await c.get(path+'/'+record['id'])).status_code==404
    await upload(c, path)
    await c.delete('/api/chat/assistants/'+aid)
    assert not (m.store.root/'assistants'/aid).exists()


async def test_file_count_limit_and_batch_atomic_validation(chat):
    m, c = chat.manager, chat.http
    path = '/api/chat/assistants/_default/files'
    response = await c.post(path, files=[('files', ('ok', b'valid')), ('files', ('bad', b'\xff'))])
    assert response.status_code==415 and (await c.get(path)).json()==[]
    response = await c.post(path, files=[('files', (str(i), b'line')) for i in range(100)])
    assert response.status_code==200 and len(response.json())==100
    assert (await c.post(path, files={'files': ('extra', b'extra')})).status_code==409
    assert len((await c.get(path)).json())==100


async def test_session_text_validation_inline_and_delete(chat):
    m, c = chat.manager, chat.http
    sid = m.create_session('_default', 'Files')['id']
    path = f'/api/chat/sessions/{sid}/uploads'
    for content in (b'\xff', b'\x00'):
        assert (await c.post(path, files={'files': ('x', content)})).status_code==415
    assert (await c.post(path, files={'files': ('x', b'x'*(2*1024*1024+1))})).status_code==413
    record = await upload(c, path, text='hello\nworld', name='a&b.txt')
    assert record['is_text'] and not record['is_image'] and record['chars']==11 and record['lines']==2
    assert (await c.get(record['url'])).text=='hello\nworld'
    large = await upload(c, path, text='a'*50000+'TAIL', name='large.txt')
    runtime = m.runtime(sid)
    runtime.send('Read', [record, large])
    await runtime.task
    history = providers.history(runtime.items[:1], chat.format)
    assert history[0]['content'][1]['text']=='<file name="a&amp;b.txt">\nhello\nworld\n</file>'
    inline = history[0]['content'][2]['text']
    assert 'TAIL' not in inline and 'a'*50000 in inline
    assert inline.endswith('\nThe rest of this file can be read with file_read.\n</file>')
    other = m.create_session('_default')['id']
    assert (await c.get(f"/api/chat/uploads/{other}/{record['id']}")).status_code==404
    await m.delete_session(sid)
    assert not Path(record['path']).exists()


async def test_file_tools_search_read_scopes_and_switches(chat):
    m, c = chat.manager, chat.http
    aid = m.create_assistant({'name': 'Docs'})['id']
    await upload(c, f'/api/chat/assistants/{aid}/files', text='assistant only', name='shared.txt')
    await upload(c, f'/api/chat/assistants/{aid}/files', text='needle\nother\nNEEDLE', name='search.txt')
    sid = m.create_session(aid)['id']
    await upload(c, f'/api/chat/sessions/{sid}/uploads', text='session wins\nline two', name='shared.txt')
    local = LocalTools(m, sid)
    assert {t['name'] for t in local.tools}=={'file_read', 'file_search'}
    result = await local.call('file_read', {'name': 'shared.txt', 'offset': 2, 'limit': 1})
    assert result=={'content': 'Total lines: 2\n2: line two', 'is_error': False, 'images': []}
    result = await local.call('file_search', {'query': 'NEEDle'})
    assert result['content']=='search.txt:1: needle\nsearch.txt:3: NEEDLE'
    assert (await local.call('file_search', {'query': 'needle', 'name': 'shared.txt'}))['content']==''
    for args in ({'name': '../index.json'}, {'name': 'shared.txt', 'offset': 0}, {'name': 'shared.txt', 'limit': 2001}):
        assert (await local.call('file_read', args))['is_error']
    second = m.create_session(aid)['id']
    assert 'assistant only' in (await LocalTools(m, second).call('file_read', {'name': 'shared.txt'}))['content']
    assert LocalTools(m, m.create_session('_default')['id']).tools==[]
    m.patch_assistant(aid, {'files': False})
    assert LocalTools(m, sid).tools==[] and 'Files\n' not in m.resolve(sid)['system_prompt']
    assert (await c.post(f'/api/chat/sessions/{sid}/uploads', files={'files': ('x', b'hello')})).status_code==415
    assert (await c.post(f'/api/chat/sessions/{sid}/uploads', files={'files': ('x.png', b'image', 'image/png')})).status_code==200
    m.patch_assistant(aid, {'files': True})
    m.patch_config(ConfigPatch(files={'enabled': False}))
    assert LocalTools(m, sid).tools==[] and 'Files\n' not in m.resolve(sid)['system_prompt']
    assert (await c.post(f'/api/chat/sessions/{sid}/uploads', files={'files': ('x', b'hello')})).status_code==415


async def test_file_tool_result_caps(chat):
    m, c = chat.manager, chat.http
    sid = m.create_session('_default')['id']
    await upload(c, f'/api/chat/sessions/{sid}/uploads', text='hit\n'*2100)
    local = LocalTools(m, sid)
    read = (await local.call('file_read', {'name': 'notes.txt', 'limit': 2000}))['content']
    assert len(read.splitlines())==2001 and read.startswith('Total lines: 2100\n1: hit')
    search = (await local.call('file_search', {'query': 'hit'}))['content']
    assert len(search.splitlines())==50 and search.endswith('notes.txt:50: hit')


async def test_memory_crud_events_isolation_and_delete(chat):
    m, c = chat.manager, chat.http
    aid = m.create_assistant({'name': 'Memory'})['id']
    path = f'/api/chat/assistants/{aid}/memory'
    assert (await c.get(path)).json()==[]
    for text in ('', 'x'*1001):
        assert (await c.post(path, json={'text': text})).status_code==422
    record = (await c.post(path, json={'text': 'Likes tea'})).json()
    assert set(record)=={'id', 'text', 'created_at', 'updated_at', 'source'} and record['source']=='user'
    assert (await c.get(path)).json()==[record]
    assert (await c.get('/api/chat/assistants/_default/memory')).json()==[]
    assert (await c.patch('/api/chat/assistants/_default/memory/'+record['id'], json={'text': 'bad'})).status_code==404
    updated = (await c.patch(path+'/'+record['id'], json={'text': 'Likes coffee'})).json()
    assert updated['text']=='Likes coffee' and updated['created_at']==record['created_at']
    assert updated['updated_at']>=record['updated_at'] and updated['source']=='user'
    assert Resources(m.store.root).memories(aid)==[updated]
    assert chat.events[-1]=={'type': 'chat_changed', 'scope': 'memory', 'assistant_id': aid}
    assert (await c.delete(path+'/'+record['id'])).json()=={'ok': True}
    assert (await c.delete(path+'/'+record['id'])).status_code==404
    await c.post(path, json={'text': 'one'})
    await c.post(path, json={'text': 'two'})
    assert (await c.delete(path)).json()=={'ok': True}
    assert (await c.get(path)).json()==[]
    await c.post(path, json={'text': 'three'})
    await c.delete('/api/chat/assistants/'+aid)
    assert not m.resources.memory_path(aid).exists()


async def test_memory_tools_prompt_order_and_switches(chat):
    m, c = chat.manager, chat.http
    sid = m.create_session('_default')['id']
    assert LocalTools(m, sid).tools==[]
    m.patch_assistant('_default', {'memory': True})
    await upload(c, '/api/chat/assistants/_default/files')
    local = LocalTools(m, sid)
    assert len(local.tools)==5
    add = await local.call('memory_add', {'text': 'Prefers tea'})
    assert not add['is_error']
    record = m.resources.memories('_default')[0]
    assert json.loads(add['content'])=={'id': record['id']} and record['source']=='assistant'
    prompt = m.resolve(sid)['system_prompt']
    assert prompt.index('Be helpful')<prompt.index('Files\n')<prompt.index('Memory\n')
    assert f"[{record['id']}] Prefers tea" in prompt and 'Do not save secrets' in prompt
    assert 'notes.txt (13 bytes, 3 lines)' in prompt
    assert not (await local.call('memory_update', {'id': record['id'], 'text': 'Prefers coffee'}))['is_error']
    assert 'Prefers coffee' in m.resolve(sid)['system_prompt']
    assert (await local.call('memory_add', {'text': ''}))['is_error']
    assert (await local.call('memory_update', {'id': 'missing', 'text': 'x'}))['is_error']
    assert not (await local.call('memory_delete', {'id': record['id']}))['is_error']
    assert m.resources.memories('_default')==[]
    m.patch_config(ConfigPatch(memory={'enabled': False}))
    assert not any(t['name'].startswith('memory_') for t in LocalTools(m, sid).tools)
    assert 'Memory\n' not in m.resolve(sid)['system_prompt']
    m.patch_config(ConfigPatch(memory={'enabled': True}))
    m.patch_assistant('_default', {'memory': False})
    assert 'Memory\n' not in m.resolve(sid)['system_prompt']
    m.patch_assistant('_default', {'memory': True, 'files': False})
    assert m.resolve(sid)['system_prompt'].startswith('Be helpful\n\nMemory\n')


async def test_memory_limit(chat):
    m, c = chat.manager, chat.http
    path = '/api/chat/assistants/_default/memory'
    records = [dict(id=str(i), text='Fact', source='user', created_at='now', updated_at='now') for i in range(199)]
    m.resources.save_memories('_default', records)
    assert (await c.post(path, json={'text': 'Last'})).status_code==200
    assert (await c.post(path, json={'text': 'Overflow'})).status_code==409
    m.patch_assistant('_default', {'memory': True})
    local = LocalTools(m, m.create_session('_default')['id'])
    assert (await local.call('memory_add', {'text': 'Overflow'}))['is_error']
    assert len(m.resources.memories('_default'))==200


async def test_local_tools_in_reply_loop(chat, monkeypatch):
    m, c = chat.manager, chat.http
    m.patch_assistant('_default', {'memory': True})
    sid = m.create_session('_default', 'Local tools')['id']
    await upload(c, '/api/chat/assistants/_default/files', text='Useful file')
    offered, histories = [], []

    async def stream(provider, name, messages, system, tools, *settings):
        offered.append(tools)
        histories.append(messages)
        if len(offered)==1:
            for i, (name, args) in enumerate([('file_read', {'name': 'notes.txt'}), ('memory_add', {'text': 'Tea fan'})]):
                yield dict(type='tool_start', id=str(i), name=name, input=args)
                yield dict(type='tool_end', id=str(i))
            yield dict(type='stop', reason='tool_calls')
        else:
            yield dict(type='text', text='Done')
            yield dict(type='stop', reason='stop')

    monkeypatch.setattr(providers, 'stream', stream)
    runtime = m.runtime(sid)
    runtime.send('Read and remember')
    await runtime.task
    names = [t['name'] for t in offered[0]]
    assert names==['file_read', 'file_search', 'memory_add', 'memory_update', 'memory_delete', 'mcp__fetch__lookup']
    tools = [i for i in runtime.items if i['kind']=='tool']
    assert len(tools)==2 and all(not i['result']['is_error'] for i in tools)
    assert '1: Useful file' in tools[0]['result']['content']
    assert 'Useful file' in json.dumps(histories[1])
    assert m.resources.memories('_default')[0]['text']=='Tea fan'
    assert chat.peer.calls==[]


async def test_recent_sessions_order_and_status(chat):
    m, c = chat.manager, chat.http
    aid = m.create_assistant({'name': 'Recent'})['id']
    assert (await c.get(f'/api/chat/assistants/{aid}')).json()['recent']==[]
    ids = [m.create_session(aid, str(i))['id'] for i in range(7)]
    m.update_session(ids[0], title='Updated oldest')
    other = m.create_session('_default')['id']
    for view in ((await c.get('/api/chat/assistants')).json()[0], (await c.get(f'/api/chat/assistants/{aid}')).json()):
        assert [s['id'] for s in view['recent']]==[ids[0], *reversed(ids[-4:])]
        assert view['recent']==m.sessions(aid)[:5]
        assert view['status']['last_session']['id']==ids[0]
    assert (await c.get('/api/chat/assistants/_default')).json()['recent']==[m.view(other)]


async def test_feature_config_roundtrip(chat):
    m, c = chat.manager, chat.http
    config = (await c.get('/api/chat/config')).json()
    assert config['titles']=={'enabled': True, 'model': '', 'prompt': ''}
    assert config['files']==config['memory']=={'enabled': True}
    assert 'title_model' not in config['defaults']
    assert (await c.patch('/api/chat/config', json={'titles': {'model': 'local/large'}})).status_code==200
    result = (await c.patch('/api/chat/config', json={'titles': {'prompt': 'Custom'}, 'files': {'enabled': False},
                                                   'memory': {'enabled': False}})).json()
    assert result['titles']=={'enabled': True, 'model': 'local/large', 'prompt': 'Custom'}
    m.config.replace_raw(m.config.path.read_text())
    assert m.config.data.files.enabled is False and m.config.data.memory.enabled is False
    assert (await c.patch('/api/chat/config', json={'titles': {'enabled': 'invalid'}})).status_code==422


def test_chat_migration(tmp_path, capsys):
    spec = importlib.util.spec_from_file_location('chat_migration', Path(__file__).parents[1]/'scripts/migrate/chat.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.migrate(tmp_path)
    path = tmp_path/'config'/'chat.toml'
    path.parent.mkdir()
    original = '# Config\n[defaults]\nmodel = "local/small" # conversation\ntitle_model = "local/large" # title\n'
    path.write_text(original)
    module.migrate(tmp_path, dry_run=True)
    assert path.read_text()==original and 'move defaults.title_model' in capsys.readouterr().out
    module.migrate(tmp_path)
    migrated = path.read_text()
    doc = tomlkit.parse(migrated)
    assert doc['titles']['model']=='local/large' and 'title_model' not in doc['defaults']
    assert doc['defaults']['model']=='local/small' and '# Config' in migrated and '# conversation' in migrated and '# title' in migrated
    assert set(doc)=={'defaults', 'titles'}
    module.migrate(tmp_path)
    assert path.read_text()==migrated


async def test_stop_reply_keeps_title_running(chat, monkeypatch):
    m = chat.manager
    entered, release = asyncio.Event(), asyncio.Event()

    async def complete(*args, **kwargs):
        entered.set()
        await release.wait()
        return 'Title after stop'

    monkeypatch.setattr(providers, 'complete', complete)
    runtime = m.runtime(m.create_session('_default')['id'])
    runtime.send('hold the reply')
    await entered.wait()
    await until(lambda: chat.peer.held)
    await runtime.stop()
    assert runtime.state=='idle' and not runtime.title_task.done()
    release.set()
    await runtime.title_task
    assert runtime.session['title']=='Title after stop'


async def test_concurrent_assistant_file_uploads_keep_both_indexes(chat):
    m = chat.manager
    entered, release = asyncio.Event(), asyncio.Event()

    class Upload:
        filename = 'one.txt'

        async def read(self, cap):
            entered.set()
            await release.wait()
            return b'one'

    pending = asyncio.create_task(m.resources.upload('_default', [Upload()]))
    await entered.wait()
    await upload(chat.http, '/api/chat/assistants/_default/files', text='two', name='two.txt')
    release.set()
    await pending
    assert {r['name'] for r in m.resources.files('_default')}=={'one.txt', 'two.txt'}


def test_chat_migration_conflict_does_not_modify_file(tmp_path):
    spec = importlib.util.spec_from_file_location('chat_migration', Path(__file__).parents[1]/'scripts/migrate/chat.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path/'config'/'chat.toml'
    path.parent.mkdir()
    original = '[defaults]\ntitle_model = "old"\n[titles]\nmodel = "new"\n'
    path.write_text(original)
    for dry_run in (True, False):
        with pytest.raises(ValueError, match='Conflicting'): module.migrate(tmp_path, dry_run=dry_run)
        assert path.read_text()==original


@pytest.mark.parametrize('format', ['openai', 'anthropic'])
def test_text_attachment_preserves_decoded_characters(tmp_path, format):
    path = tmp_path/'text'
    path.write_bytes('你好\r\nworld'.encode())
    messages = providers.history([{'kind': 'user', 'text': '',
                                   'attachments': [{'name': 'text', 'path': str(path), 'is_text': True}]}], format)
    assert messages[0]['content']==[{'type': 'text', 'text': '<file name="text">\n你好\r\nworld\n</file>'}]
