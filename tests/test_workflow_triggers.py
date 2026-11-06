import base64
from unittest.mock import AsyncMock

import pytest

from server.workflow.db import Database
from server.workflow.engine.runner import prepare_inputs
from server.workflow.sdk import StepError


@pytest.fixture
def trigger(logged):
    workflow = logged.post('/api/workflow/workflows', json={'name': 'Webhook', 'definition': {
        'inputs': [{'name': 'name', 'type': 'text', 'default': 'world'},
                   {'name': 'count', 'type': 'number', 'default': 2}],
        'blocks': [{'id': 't', 'type': 'builtin.text', 'params': {'text': ['Hello ', {'ref': '@input', 'field': 'name'}]}}],
    }}).json()
    path = f"/api/workflow/workflows/{workflow['id']}/trigger"
    config = logged.get(path).json()
    assert config['enabled'] is False and config['last_used_at'] is None
    assert len(base64.urlsafe_b64decode(config['token'] + '=')) == 32
    assert logged.get(path).json() == config
    assert logged.patch(path, json={'enabled': True}).json()['enabled'] is True
    return workflow['id'], path, config


@pytest.mark.parametrize('auth', ['bearer', 'header', 'query'])
def test_public_trigger_auth_inputs_and_wait(logged, trigger, auth):
    wid, path, config = trigger
    logged.cookies.clear()
    headers, params = {}, {'wait': '1'}
    if auth == 'bearer': headers['Authorization'] = 'Bearer ' + config['token']
    elif auth == 'header': headers['X-Workflow-Token'] = config['token']
    else: params['token'] = config['token']
    response = logged.post(config['path'], headers=headers, params=params,
                           json={'name': 'Sam', 'count': '3.5', 'unknown': 'ignored'})
    assert response.status_code == 200, response.text
    run = response.json()
    assert run['done'] and run['status'] == 'success' and run['result'] == 'Hello Sam'
    assert run['trigger'] == 'webhook' and run['workflow_id'] == wid
    assert run['inputs'] == {'name': 'Sam', 'count': 3.5}
    assert run['run_id'] == run['id'] and 'snapshot' not in run
    assert logged.get(path).status_code == 401
    assert logged.get(f"/api/workflow/runs/{run['id']}").status_code == 401


def test_trigger_disabled_bad_token_and_unknown(logged, trigger):
    wid, path, config = trigger
    assert logged.post('/api/workflow/trigger/unknown').status_code == 404
    assert logged.get('/api/workflow/workflows/unknown/trigger').status_code == 404
    assert logged.patch('/api/workflow/workflows/unknown/trigger', json={'enabled': True}).status_code == 404
    assert logged.post('/api/workflow/workflows/unknown/trigger/regenerate').status_code == 404
    for kwargs in ({}, {'headers': {'Authorization': 'Bearer wrong'}},
                   {'headers': {'X-Workflow-Token': 'wrong'}}, {'params': {'token': 'wrong'}},
                   {'params': {'token': '错误'}}):
        assert logged.post(config['path'], **kwargs).status_code == 401
    assert logged.get(path).json()['last_used_at'] is None
    assert logged.patch(path, json={'enabled': False}).json()['enabled'] is False
    assert logged.post(config['path'], params={'token': config['token']}).status_code == 403
    other = logged.post('/api/workflow/workflows', json={'name': 'No trigger'}).json()['id']
    assert logged.post(f'/api/workflow/trigger/{other}').status_code == 403


def test_trigger_regenerate_management_auth_and_no_wait(logged, app, trigger):
    wid, path, config = trigger
    assert logged.patch('/api/config', json={'server': {'api_key': 'server-key'}}).status_code == 200
    logged.cookies.clear()
    assert logged.patch(path, json={'enabled': False}).status_code == 401
    assert logged.post(path + '/regenerate').status_code == 401
    headers = {'Authorization': 'Bearer server-key'}
    rotated = logged.post(path + '/regenerate', headers=headers).json()
    assert rotated['token'] != config['token'] and rotated['enabled']
    assert logged.get(path, headers=headers).json() == rotated
    assert logged.post(config['path'], params={'token': config['token']}).status_code == 401
    assert logged.post(config['path'], headers=headers).status_code == 401
    result = logged.post(rotated['path'], params={'token': rotated['token']})
    assert result.status_code == 202 and result.json()['status'] == 'queued'
    rid = result.json()['run_id']
    manager = app.state.core.modules['workflow']
    assert logged.portal.call(manager.wait, rid, 20)
    run = logged.get(f'/api/workflow/runs/{rid}', headers=headers).json()
    assert run['inputs'] == {'name': 'world', 'count': 2} and run['trigger'] == 'webhook'
    assert logged.get(path, headers=headers).json()['last_used_at'] > 0
    assert logged.patch(path, json={'enabled': False}, headers=headers).json()['enabled'] is False


def test_trigger_body_and_input_errors(logged, trigger):
    wid, path, config = trigger
    params = {'token': config['token'], 'wait': '1'}
    for body in ('{', '[]', 'null', '"text"', '42', b'\xff'):
        assert logged.post(config['path'], params=params, content=body).status_code == 400
    bad = logged.post(config['path'], params=params, json={'count': 'not a number'})
    assert bad.status_code == 400 and 'number' in bad.json()['detail']
    assert logged.get(path).json()['last_used_at'] is None
    assert logged.get('/api/workflow/runs').json() == []
    definition = {'inputs': [{'name': 'name', 'type': 'text', 'required': True}], 'blocks': []}
    logged.put(f'/api/workflow/workflows/{wid}', json={'definition': definition})
    assert logged.post(config['path'], params=params).status_code == 400
    assert logged.post(f'/api/workflow/workflows/{wid}/run', json={'wait': True}).status_code == 400
    assert logged.post(config['path'], params=params, json={'name': 'Sam'}).json()['done']


def test_trigger_body_limit(logged, trigger):
    _, _, config = trigger
    params = {'token': config['token']}
    prefix, suffix = b'{"unknown":"', b'"}'
    body = prefix + b'x' * (1024 * 1024 - len(prefix) - len(suffix)) + suffix
    assert logged.post(config['path'], params=params, content=body).status_code == 202
    assert logged.post(config['path'], params=params, content=body + b' ').status_code == 413
    assert logged.post(config['path'], params=params, content=iter([body, b' '])).status_code == 413


def test_trigger_wait_timeout_and_query_limits(logged, app, trigger, monkeypatch):
    wid, _, config = trigger
    manager = app.state.core.modules['workflow']
    wait = AsyncMock(return_value=False)
    monkeypatch.setattr(manager, 'wait', wait)
    params = {'token': config['token'], 'wait': '1'}
    response = logged.post(config['path'], params=params)
    assert response.status_code == 200 and response.json()['done'] is False
    assert wait.call_args.args[1] == 60
    assert logged.post(config['path'], params={**params, 'timeout': 300}).status_code == 200
    assert wait.call_args.args[1] == 300
    for timeout in (301, 0, -1, 'nan', 'inf'):
        assert logged.post(config['path'], params={**params, 'timeout': timeout}).status_code == 422


def test_trigger_wait_timeout_keeps_run_active(logged, trigger):
    wid, _, config = trigger
    logged.put(f'/api/workflow/workflows/{wid}', json={'definition': {
        'inputs': [], 'blocks': [{'id': 'ask', 'type': 'builtin.ask_input', 'params': {'prompt': 'Name?'}}],
    }})
    response = logged.post(config['path'], params={'token': config['token'], 'wait': 1, 'timeout': 0.05})
    assert response.status_code == 200
    run = response.json()
    assert run['done'] is False and run['status'] == 'waiting_input'
    assert logged.post(f"/api/workflow/runs/{run['id']}/cancel").status_code == 200


def test_trigger_delete_cascade_and_duplicate_isolation(logged, app, trigger):
    wid, path, config = trigger
    dup = logged.post(f'/api/workflow/workflows/{wid}/duplicate').json()['id']
    copy = logged.get(f'/api/workflow/workflows/{dup}/trigger').json()
    assert not copy['enabled'] and copy['token'] != config['token']
    assert logged.delete(f'/api/workflow/workflows/{wid}').status_code == 200
    manager = app.state.core.modules['workflow']
    assert logged.portal.call(manager.db.fetchone, 'SELECT * FROM triggers WHERE workflow_id=?', (wid,)) is None
    assert logged.get(path).status_code == 404
    assert logged.post(config['path'], params={'token': config['token']}).status_code == 404


async def test_trigger_schema_upgrades_existing_database(tmp_path):
    import sqlite3
    path = tmp_path / 'app.db'
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE workflows(id TEXT PRIMARY KEY, name TEXT, definition TEXT)")
        conn.execute("INSERT INTO workflows VALUES('wf', 'Existing', '{}')")
    db = Database(path)
    await db.open()
    await db.execute("INSERT INTO triggers VALUES('wf',1,'secret',1,NULL)")
    await db.close()
    await db.open()
    assert (await db.fetchone("SELECT * FROM triggers"))['token'] == 'secret'
    assert (await db.fetchone("SELECT * FROM workflows"))['name'] == 'Existing'
    await db.execute("DELETE FROM workflows WHERE id='wf'")
    assert await db.fetchall("SELECT * FROM triggers") == []
    await db.close()


def test_required_inputs_keep_false_and_zero():
    definition = {'inputs': [{'name': 'flag', 'type': 'bool', 'required': True},
                             {'name': 'count', 'type': 'number', 'required': True}]}
    assert prepare_inputs(definition, {'flag': False, 'count': 0}) == {'flag': False, 'count': 0}
    with pytest.raises(StepError, match='count is required'):
        prepare_inputs(definition, {})
