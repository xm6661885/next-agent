import json

import pytest


@pytest.fixture
def authed(logged): return logged

from server.workflow.engine.variables import Scope, build_tree, flatten, coerce, find_invalid_refs, resolve_text, resolve_value, truthy
from server.workflow.engine.expr import evaluate
from server.workflow.sdk import StepError


def ref(b, field=None, **kw):
    d = {"ref": b}
    if field:
        d["field"] = field
    d.update(kw)
    return d


# ------------------------------------------------------------ Pure functions
def test_resolve_text_and_value():
    s = Scope({"topic": "AI"}, {"K": "v"})
    s.outputs["b1"] = {"fields": {"result": "hello", "data": {"a": [1, {"x": 2}]}}, "default": "result"}
    assert resolve_text(["a-", ref("b1"), "-", ref("@input", "topic"), ref("@env", "K")], s) == "a-hello-AIv"
    assert resolve_value([ref("b1", "data")], s) == {"a": [1, {"x": 2}]}
    assert resolve_value([ref("b1", "data", path=["a", 1, "x"])], s) == 2
    assert resolve_value(["x", ref("b1")], s) == "xhello"
    with pytest.raises(StepError):
        resolve_text([ref("nope")], s)
    with pytest.raises(StepError):
        resolve_text([ref("@loop", "item")], s)


def test_coerce():
    assert coerce("3", "number") == 3 and coerce("3.5", "number") == 3.5 and coerce("", "number") is None
    assert coerce("[1,2]", "list") == [1, 2]
    assert coerce("a\n\nb", "list") == ["a", "b"]
    assert coerce('{"a":1}', "json") == {"a": 1}
    with pytest.raises(StepError):
        coerce("{bad", "json")
    assert coerce("false", "bool") is False and truthy("True") and not truthy("")


def test_expr():
    s = Scope({}, {})
    s.outputs["b1"] = {"fields": {"result": "hello world", "s": {"decision": True}}, "default": "result"}
    assert evaluate(["len(", ref("b1"), ") > 5 and 'world' in ", ref("b1")], s) is True
    assert evaluate([ref("b1", "s", path=["decision"])], s) is True
    assert evaluate(["v1 if false else 2".replace("v1", "1")], s) == 2
    with pytest.raises(StepError):
        evaluate(["__import__('os')"], s)
    with pytest.raises(StepError):
        evaluate([""], s)


def test_find_invalid_refs():
    blocks = [
        {"id": "a", "type": "builtin.text", "params": {"text": [ref("b")]}},  # b is below
        {"id": "b", "type": "builtin.text", "params": {}},
        {"id": "c", "type": "core.repeat", "params": {"count": 2}, "body": [
            {"id": "d", "type": "builtin.text", "params": {"text": [ref("@loop", "item"), ref("b")]}},
        ]},
        {"id": "e", "type": "builtin.text", "params": {"text": [ref("d"), ref("@loop", "item")]}},  # d is inside a loop / not inside the loop
    ]
    bad = {(p["block_id"], p["ref"]) for p in find_invalid_refs(blocks)}
    assert bad == {("a", "b"), ("e", "d"), ("e", "@loop")}


# ------------------------------------------------------------ End to end
def make_wf(client, blocks, inputs=None):
    wf = client.post("/api/workflow/workflows", json={"name": "t", "definition": {"inputs": inputs or [], "blocks": blocks}}).json()
    return wf["id"]


def run(client, wid, **kw):
    r = client.post(f"/api/workflow/workflows/{wid}/run", json={"wait": True, "timeout": 20, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def events(client, run_id):
    r = client.get(f"/api/workflow/runs/{run_id}/events")
    assert r.status_code == 200
    out = []
    for line in r.text.splitlines():
        if line.startswith("data: "):
            out.append(json.loads(line[6:]))
    return out


def test_linear_run_and_sse_replay(authed):
    wid = make_wf(authed, [
        {"id": "b1", "type": "builtin.text", "params": {"text": ["Hello ", ref("@input", "name")]}},
        {"id": "b2", "type": "builtin.show", "params": {"text": ["[", ref("b1"), "]"]}},
    ], inputs=[{"name": "name", "type": "text", "default": "world"}])
    r = run(authed, wid)
    assert r["status"] == "success" and r["done"]
    assert r["result"] == "[Hello world]"  # without a Stop card, the last card's output is used
    assert r["inputs"] == {"name": "world"}
    evs = events(authed, r["run_id"])
    types = [e["type"] for e in evs]
    assert types[0] == "run_queued" and types[-1] == "run_finished"
    assert types.count("step_output") == 2
    assert [e["seq"] for e in evs] == list(range(1, len(evs) + 1))
    # Last-Event-ID resume
    tail = authed.get(f"/api/workflow/runs/{r['run_id']}/events", headers={"Last-Event-ID": "3"}).text
    assert "id: 1\n" not in tail and "id: 4\n" in tail


def test_if_repeat_stop(authed):
    wid = make_wf(authed, [
        {"id": "l", "type": "builtin.text", "params": {"text": "x\ny\nz"}},
        {"id": "sp", "type": "builtin.split_text", "params": {"text": [ref("l")], "sep": "\\n"}},
        {"id": "r", "type": "core.repeat_each", "params": {"items": [ref("sp", "list")]}, "body": [
            {"id": "i", "type": "core.if", "params": {"expr": [ref("@loop", "index"), " == 2"]},
             "then": [{"id": "t", "type": "builtin.text", "params": {"text": ["two:", ref("@loop", "item")]}}],
             "else": [{"id": "e", "type": "builtin.text", "params": {"text": ["other:", ref("@loop", "item")]}}]},
        ]},
        {"id": "s", "type": "builtin.stop_output", "params": {"value": [ref("r")]}},
        {"id": "never", "type": "builtin.show", "params": {"text": "should not run"}},
    ])
    r = run(authed, wid)
    assert r["status"] == "success", r
    assert r["result"] == ["other:x", "two:y", "other:z"]
    evs = events(authed, r["run_id"])
    assert not any(e["block_id"] == "never" for e in evs)
    assert sum(e["type"] == "loop_iteration" for e in evs) == 3


def test_failure_and_invalid_refs(authed):
    wid = make_wf(authed, [{"id": "a", "type": "builtin.text", "params": {"text": [ref("zzz")]}}])
    r = run(authed, wid)
    assert r["status"] == "failed" and "reference" in r["error"]
    wid = make_wf(authed, [
        {"id": "a", "type": "builtin.get_time", "params": {"tz": "Nope/Zone"}},
        {"id": "b", "type": "builtin.show", "params": {"text": "x"}},
    ])
    r = run(authed, wid)
    assert r["status"] == "failed" and "Unknown timezone" in r["error"]
    wid = make_wf(authed, [
        {"id": "a", "type": "builtin.get_time", "params": {"tz": "Nope/Zone"}, "continue_on_error": True},
        {"id": "b", "type": "builtin.show", "params": {"text": ["got ", ref("a")]}},
    ])
    r = run(authed, wid)
    assert r["status"] == "success" and "Unknown timezone" in r["result"]


def test_rerun_from_block_reuses_outputs(authed):
    wid = make_wf(authed, [
        {"id": "t", "type": "builtin.get_time", "params": {"format": "%f"}},
        {"id": "s", "type": "builtin.show", "params": {"text": [ref("t")]}},
    ])
    first = run(authed, wid)
    second = authed.post(f"/api/workflow/runs/{first['run_id']}/rerun", params={"from_block": "s"}).json()
    evs = events(authed, second["run_id"])
    done = [e for e in evs if e["type"] == "run_finished"][0]
    assert done["data"]["status"] == "success"
    assert done["data"]["result"] == first["result"]  # reused the upstream time
    assert any(e["data"].get("cached") for e in evs if e["type"] == "step_output")
    # single card test
    only = run(authed, wid, base_run_id=first["run_id"], only_block="s")
    assert only["result"] == first["result"]


def test_cancel_and_timeout(authed):
    # use an Ask for input card to leave the run in a waiting state
    wid = make_wf(authed, [{"id": "q", "type": "builtin.ask_input", "params": {"prompt": "Name?"}},
                           {"id": "s", "type": "builtin.show", "params": {"text": ["hi ", ref("q")]}}])
    rid = authed.post(f"/api/workflow/workflows/{wid}/run", json={}).json()["run_id"]
    import time
    for _ in range(50):
        if authed.get(f"/api/workflow/runs/{rid}").json()["status"] == "waiting_input":
            break
        time.sleep(0.05)
    assert authed.get(f"/api/workflow/runs/{rid}").json()["status"] == "waiting_input"
    assert authed.post(f"/api/workflow/runs/{rid}/input", json={"values": {"text": "Bob"}}).status_code == 200
    for _ in range(50):
        if authed.get(f"/api/workflow/runs/{rid}").json()["status"] == "success":
            break
        time.sleep(0.05)
    assert authed.get(f"/api/workflow/runs/{rid}").json()["result"] == "hi Bob"
    # cancel
    rid = authed.post(f"/api/workflow/workflows/{wid}/run", json={}).json()["run_id"]
    for _ in range(50):
        if authed.get(f"/api/workflow/runs/{rid}").json()["status"] == "waiting_input":
            break
        time.sleep(0.05)
    assert authed.post(f"/api/workflow/runs/{rid}/cancel").status_code == 200
    for _ in range(50):
        if authed.get(f"/api/workflow/runs/{rid}").json()["status"] == "cancelled":
            break
        time.sleep(0.05)
    assert authed.get(f"/api/workflow/runs/{rid}").json()["status"] == "cancelled"


def test_subworkflow(authed):
    child = authed.post("/api/workflow/workflows", json={"name": "child", "definition": {
        "inputs": [{"name": "x", "type": "text"}],
        "blocks": [{"id": "c1", "type": "builtin.stop_output", "params": {"value": ["child:", ref("@input", "x")]}}]}}).json()["id"]
    wid = make_wf(authed, [
        {"id": "p", "type": "builtin.run_workflow", "params": {"workflow": child, "inputs": ['{"x": "', ref("@env", "NOPE"), 'q"}']}},
        {"id": "s", "type": "builtin.show", "params": {"text": [ref("p")]}},
    ])
    r = run(authed, wid)
    assert r["status"] == "success" and r["result"] == "child:q"


def test_save_file(authed, tmp_path):
    f = tmp_path / "sub" / "a.txt"
    wid = make_wf(authed, [{"id": "s", "type": "builtin.save_file", "params": {"path": str(f), "content": "hi", "overwrite": False}}])
    assert run(authed, wid)["status"] == "success" and f.read_text() == "hi"
    r = run(authed, wid)
    assert r["status"] == "failed" and "already exists" in r["error"]


async def test_alert_requests_input():
    from server.workflow.plugins_core.alert.plugin import AlertCard

    seen = {}

    class C:
        async def request_input(self, prompt, fields, alert=None):
            seen.update(alert)
            return {}

    r = await AlertCard().run(C(), {"title": "T", "message": "M", "ok_text": " ", "show_cancel": True})
    assert r == {"ok": True} and seen == {"title": "T", "message": "M", "ok_text": "OK", "show_cancel": True}



def test_build_tree_roundtrip():
    nested = [
        {"id": "r", "type": "core.repeat", "params": {"count": 2}, "body": [
            {"id": "i", "type": "core.if", "params": {"expr": ["1"]},
             "then": [{"id": "t", "type": "builtin.text"}], "else": [{"id": "e", "type": "builtin.text"}]},
        ]},
    ]
    flat = flatten(nested)
    assert [b["type"] for b in flat] == ["core.repeat", "core.if", "builtin.text", "core.else", "builtin.text", "core.end_if", "core.end_repeat"]
    tree = build_tree(flat)
    assert tree[0]["body"][0]["then"][0]["id"] == "t" and tree[0]["body"][0]["else"][0]["id"] == "e"


def test_build_tree_unbalanced():
    with pytest.raises(StepError):
        build_tree([{"id": "r", "type": "core.repeat"}])
    with pytest.raises(StepError):
        build_tree([{"id": "x", "type": "core.end_repeat", "group": "r"}])


def test_vars_and_flat_loop(authed):
    blocks = [
        {"id": "d", "type": "builtin.var_define", "params": {"name": "n", "type": "number", "value": ["1"]}},
        {"id": "r", "type": "core.repeat", "params": {"count": 3}},
        {"id": "s", "type": "builtin.var_set", "params": {"name": "n", "op": "add", "value": [ref("@loop", "index")]}},
        {"id": "rz", "type": "core.end_repeat", "group": "r"},
        {"id": "sh", "type": "builtin.shell", "params": {"command": ["echo $NW_T-", ref("@var", "n")]}},
        {"id": "o", "type": "builtin.stop_output", "params": {"value": [ref("sh")]}},
    ]
    authed.patch("/api/workflow/settings", json={"env": {"NW_T": "hi"}})
    r = authed.post("/api/workflow/workflows", json={"name": "v", "definition": {"inputs": [], "blocks": blocks}}).json()
    out = authed.post(f"/api/workflow/workflows/{r['id']}/run", json={"wait": True}).json()
    assert out.get("result") == "hi-7", out


def test_crud_settings_raw_and_feed(logged, app, tmp_path, monkeypatch):
    import tomlkit
    core = app.state.core
    manager = core.modules['workflow']
    feed = []
    monkeypatch.setattr(core, 'emit', feed.append)
    prefix = '/api/workflow'
    group = logged.post(prefix+'/groups', json={'name': 'Daily'}).json()
    wf = logged.post(prefix+'/workflows', json={'name': 'a', 'group_id': group['id']}).json()
    dup = logged.post(prefix+f"/workflows/{wf['id']}/duplicate").json()
    assert dup['name']=='a copy'
    updated = logged.put(prefix+f"/workflows/{wf['id']}", json={'name': 'b', 'clear_group': True}).json()
    assert updated['name']=='b' and updated['group_id'] is None
    exported = logged.get(prefix+f"/workflows/{wf['id']}/export").json()
    assert exported['format']=='next-workflow/1'
    imported = logged.post(prefix+'/workflows/import', json=exported).json()
    assert imported['name']=='b'
    assert logged.put(prefix+'/workflows/reorder', json={'ids': [dup['id'], wf['id'], imported['id']]}).status_code==200
    assert logged.put(prefix+'/groups/reorder', json={'ids': [group['id']]}).status_code==200
    assert logged.put(prefix+f"/groups/{group['id']}", json={'name': 'Weekly'}).status_code==200
    assert logged.get(prefix+'/groups').json()[0]['name']=='Weekly'
    assert logged.delete(prefix+f"/groups/{group['id']}").status_code==200
    assert logged.get(prefix+f"/workflows/{dup['id']}").json()['group_id'] is None
    assert logged.delete(prefix+f"/workflows/{imported['id']}").status_code==200
    assert logged.get(prefix+f"/workflows/{imported['id']}").status_code==404
    assert feed==[{'type': 'workflow_changed', 'module': 'workflow'}]*10
    assert core.modules['overview_workflow']()=={'workflows': 2, 'runs': 0}
    raw = logged.get('/api/config/raw?file=workflow').json()
    content = raw['content'].replace('agent_concurrency = 1', 'agent_concurrency = 2 # preserved')
    assert logged.put('/api/config/raw?file=workflow', json={'content': content}).status_code==200
    assert manager.limiter.limit==2
    body = {'agent_concurrency': 3, 'run_retention': 0, 'default_cwd': str(tmp_path/'cwd'),
            'plugin_watch': True, 'env': {'WORKFLOW_TEST': 'yes'}}
    assert logged.patch(prefix+'/settings', json=body).json()==body
    saved = tomlkit.parse(manager.config.path.read_text())
    assert saved['server']['agent_concurrency']==3 and saved['env']==body['env']
    assert '# preserved' in manager.config.path.read_text() and manager.plugins.watching
    assert logged.patch(prefix+'/settings', json={'plugin_watch': False}).status_code==200
    assert not manager.plugins.watching
    before = manager.config.path.read_bytes()
    assert logged.patch(prefix+'/settings', json={'agent_concurrency': 17}).status_code==422
    assert logged.patch(prefix+'/settings', json={'env': {'BAD=KEY': 'x'}}).status_code==422
    assert manager.config.path.read_bytes()==before
    wid = make_wf(logged, [{'id': 's', 'type': 'builtin.shell', 'params': {'command': 'printf "%s:%s" "$WORKFLOW_TEST" "$PWD"'}}])
    answer = run(logged, wid)
    assert answer['result']==f'yes:{tmp_path / "cwd"}'
    assert [e['status'] for e in feed if e['type']=='run_state']==['queued', 'running', 'success']
    assert all(e['module']=='workflow' for e in feed)
    listed = logged.get(prefix+'/workflows').json()
    assert next(w for w in listed if w['id']==wid)['last_status']=='success'
    assert logged.get(prefix+f"/runs/{answer['run_id']}/outputs").json()[0]['fields']['stdout']==answer['result']
    assert logged.delete(prefix+f"/runs/{answer['run_id']}").status_code==200
    assert core.modules['overview_workflow']()=={'workflows': 3, 'runs': 0}
    tables = logged.portal.call(manager.db.fetchall, "SELECT name FROM sqlite_master WHERE type='table'")
    assert {t['name'] for t in tables}=={'groups', 'workflows', 'runs', 'run_events', 'step_outputs'}


def test_auth_and_api_trigger(logged, app):
    wid = make_wf(logged, [{'id': 's', 'type': 'builtin.text', 'params': {'text': 'pong'}}])
    assert logged.patch('/api/config', json={'server': {'api_key': 'workflow-test-key'}}).status_code==200
    logged.cookies.clear()
    for path in ('groups', 'workflows', 'runs', 'plugins', 'settings', 'console'):
        assert logged.get('/api/workflow/'+path).status_code==401
    headers = {'Authorization': 'Bearer workflow-test-key'}
    path = f'/api/workflow/workflows/{wid}/run'
    assert logged.post(path, json={'wait': True}, headers={'Authorization': 'Bearer wrong'}).status_code==401
    result = logged.post(path, json={'wait': True}, headers=headers).json()
    assert result['status']=='success' and result['result']=='pong' and result['trigger']=='api'
    rerun = logged.post(f"/api/workflow/runs/{result['id']}/rerun", headers=headers).json()
    assert logged.get(f"/api/workflow/runs/{rerun['run_id']}", headers=headers).json()['trigger']=='api'
    assert logged.get('/api/workflow/settings', headers=headers).status_code==200


def test_user_plugins_reload_and_isolation(logged, app):
    manager = app.state.core.modules['workflow']
    directory = manager.workspace_dir.parent/'plugins'
    good, bad = directory/'hello', directory/'broken'
    good.mkdir(); bad.mkdir()
    (good/'plugin.py').write_text(
        "import os\n"
        "from server.workflow.sdk import Plugin, Input, Output, StepError\n"
        "class Hello(Plugin):\n"
        "    id='user.hello'; name='Hello'; requires_env=['TEST_PLUGIN_KEY']\n"
        "    inputs=[Input('who', default='world')]; outputs=[Output('result', default=True)]\n"
        "    async def run(self, ctx, p):\n"
        "        assert os.environ['TEST_PLUGIN_KEY']==ctx.env['TEST_PLUGIN_KEY']\n"
        "        return {'result': ctx.env['TEST_PLUGIN_KEY'] + p['who']}\n")
    (bad/'plugin.py').write_text('import nonexistent_workflow_module\n')
    result = logged.post('/api/workflow/plugins/reload').json()
    assert len(result['errors'])==1 and result['errors'][0]['name']=='broken'
    plugins = logged.get('/api/workflow/plugins').json()
    card = next(p for p in plugins['plugins'] if p['id']=='user.hello')
    assert card['missing_env']==['TEST_PLUGIN_KEY'] and card['source']=='user/hello'
    assert 'builtin.agent' not in {p['id'] for p in plugins['plugins']}
    wid = make_wf(logged, [{'id': 'h', 'type': 'user.hello'}])
    assert run(logged, wid)['status']=='failed'
    logged.patch('/api/workflow/settings', json={'env': {'TEST_PLUGIN_KEY': 'hello '}})
    assert run(logged, wid)['result']=='hello world'
    assert logged.post('/api/workflow/plugins/install-deps', json={'folder': 'user/../bad'}).status_code==400
    assert logged.post('/api/workflow/plugins/install-deps', json={'folder': 'user/hello'}).status_code==404
