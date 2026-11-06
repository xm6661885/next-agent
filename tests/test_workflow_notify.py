import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from server.workflow.engine.variables import Scope, resolve_params
from server.workflow.plugins_extra.notify.plugin import NotifyCard
from server.workflow.sdk import StepError


@pytest.fixture(autouse=True)
def process(monkeypatch):
    # Every test in this file intercepts subprocess creation; notify is never executed.
    proc = SimpleNamespace(returncode=0, communicate=AsyncMock(return_value=(b'accepted\n', b'')),
                           kill=Mock(), wait=AsyncMock())
    create = AsyncMock(return_value=proc)
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', create)
    return create, proc


def params(**values):
    return resolve_params(NotifyCard.inputs, {'text': 'Body', **values}, Scope({}, {}))


def context(tmp_path):
    return SimpleNamespace(default_cwd=tmp_path, env={'NOTIFY_URL': 'http://notify.test', 'EMPTY': ''})


async def test_notify_text_stdin_environment_and_output(process, tmp_path, monkeypatch):
    create, proc = process
    monkeypatch.setenv('PARENT_ENV', 'inherited')
    output = await NotifyCard().run(context(tmp_path), params())
    assert output == {'ok': True, 'output': 'accepted\n'}
    assert create.call_args.args == ('notify', '-')
    kwargs = create.call_args.kwargs
    assert kwargs['env']['NOTIFY_URL'] == 'http://notify.test'
    assert kwargs['env']['PARENT_ENV'] == 'inherited' and kwargs['env']['EMPTY'] == ''
    assert kwargs['stdin'] == kwargs['stdout'] == kwargs['stderr'] == asyncio.subprocess.PIPE
    proc.communicate.assert_awaited_once_with(b'Body')
    proc.kill.assert_not_called()


async def test_notify_title_markdown_topic_and_shell_characters(process, tmp_path):
    create, proc = process
    text = 'First\n$(do not execute) `literal` & |\n'
    await NotifyCard().run(context(tmp_path), params(text=text, title='Title', markdown=True, topic='deploy'))
    assert create.call_args.args == ('notify', '-', '--markdown')
    proc.communicate.assert_awaited_once_with(b'Title\nFirst\n$(do not execute) `literal` & | #deploy')


@pytest.mark.parametrize('attachment,limit', [('image', 10), ('file', 50)])
@pytest.mark.parametrize('relative', [True, False])
async def test_notify_attachment_limits_and_paths(process, tmp_path, attachment, limit, relative):
    create, _ = process
    path = tmp_path / 'attachment with spaces.bin'
    with path.open('wb') as f:
        f.truncate(limit * 1024 * 1024)
    raw = path.name if relative else str(path)
    await NotifyCard().run(context(tmp_path), params(attachment=attachment, path=raw))
    assert create.call_args.args == ('notify', '-', '--' + attachment, str(path))
    create.reset_mock()
    with path.open('ab') as f:
        f.write(b'x')
    with pytest.raises(StepError, match=f'exceeds {limit} MiB'):
        await NotifyCard().run(context(tmp_path), params(attachment=attachment, path=raw))
    create.assert_not_called()


@pytest.mark.parametrize('path,error', [('', 'required'), ('  ', 'required'), ('missing', 'not a file'), ('.', 'not a file')])
async def test_notify_rejects_missing_attachment(process, tmp_path, path, error):
    with pytest.raises(StepError, match=error):
        await NotifyCard().run(context(tmp_path), params(attachment='image', path=path))
    process[0].assert_not_called()


async def test_notify_ignores_path_without_attachment(process, tmp_path):
    await NotifyCard().run(context(tmp_path), params(path='missing'))
    assert process[0].call_args.args == ('notify', '-')


def test_notify_requires_text():
    with pytest.raises(StepError, match='required'):
        params(text='')


async def test_notify_rejects_invalid_attachment(process, tmp_path):
    with pytest.raises(StepError, match='Attachment must be'):
        await NotifyCard().run(context(tmp_path), params(attachment='video'))
    process[0].assert_not_called()


async def test_notify_nonzero_includes_stdout_and_stderr(process, tmp_path):
    _, proc = process
    proc.returncode = 2
    proc.communicate.return_value = (b'notify rejected\n', b'bad argument\n')
    with pytest.raises(StepError, match='notify rejected\nbad argument\n'):
        await NotifyCard().run(context(tmp_path), params())


@pytest.mark.parametrize('error', [asyncio.TimeoutError, asyncio.CancelledError])
async def test_notify_timeout_and_cancel_reap_process(process, tmp_path, error):
    _, proc = process
    proc.returncode = None
    proc.communicate.side_effect = error
    with pytest.raises(StepError if error is asyncio.TimeoutError else asyncio.CancelledError):
        await NotifyCard().run(context(tmp_path), params())
    proc.kill.assert_called_once()
    proc.wait.assert_awaited_once()


def test_extra_discovery_schema_and_execution(logged, process):
    response = logged.get('/api/workflow/plugins').json()
    assert response['errors'] == []
    cards = {p['id']: p for p in response['plugins']}
    card = cards['extra.notify']
    assert card['source'] == 'extra/notify' and cards['builtin.text']['source'] == 'core/text'
    assert card['version'] == '1.0.0' and card['requires_env'] == [] and not card['uses_agent_slot']
    inputs = {i['name']: i for i in card['inputs']}
    assert inputs['text']['required'] and inputs['text']['magic'] and inputs['text']['multiline']
    assert inputs['topic']['advanced'] and inputs['path']['magic']
    assert inputs['attachment']['options'] == ['none', 'image', 'file']
    workflow = logged.post('/api/workflow/workflows', json={'definition': {
        'inputs': [{'name': 'body', 'type': 'text', 'default': 'Hello'}],
        'blocks': [{'id': 'n', 'type': 'extra.notify', 'params': {'text': [{'ref': '@input', 'field': 'body'}]}}],
    }}).json()
    result = logged.post(f"/api/workflow/workflows/{workflow['id']}/run", json={'wait': True}).json()
    assert result['status'] == 'success' and result['result'] is True
    process[1].communicate.assert_awaited_once_with(b'Hello')
