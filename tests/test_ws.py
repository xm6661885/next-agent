from server.config import now

def test_resume_replay_snapshot_and_subscribers(logged,app):
    sid=app.state.index.create('claude')['id']; r=app.state.manager.get_or_create(sid)
    headers={'origin':'http://testserver'}
    with logged.websocket_connect(f'/ws/sessions/{sid}',headers=headers) as ws1:
        ws1.send_json({'type':'resume','seq':0})
        assert ws1.receive_json()['type']=='snapshot'
        with logged.websocket_connect(f'/ws/sessions/{sid}',headers=headers) as ws2:
            ws2.send_json({'type':'resume','seq':0})
            assert ws2.receive_json()['type']=='snapshot'
            ws1.send_json({'type':'ping'})
            assert ws1.receive_json()['type']=='pong'
            logged.portal.call(r.emit,{'type':'item','item':{'id':'notice1','kind':'notice','ts':now(),'level':'info','text':'hello'}})
            assert ws1.receive_json()['item']['id']=='notice1'
            assert ws2.receive_json()['item']['id']=='notice1'
    assert r.state=='offline'
    logged.portal.call(r.emit,{'type':'item','item':{'id':'notice2','kind':'notice','ts':now(),'level':'info','text':'again'}})
    with logged.websocket_connect(f'/ws/sessions/{sid}',headers=headers) as ws:
        ws.send_json({'type':'resume','seq':1})
        assert ws.receive_json()['type']=='item'
    for i in range(2001): logged.portal.call(r.emit,{'type':'state','state':'offline','queue_position':0})
    with logged.websocket_connect(f'/ws/sessions/{sid}',headers=headers) as ws:
        ws.send_json({'type':'resume','seq':1})
        assert ws.receive_json()['type']=='snapshot'

def test_disconnect_does_not_stop_runtime(logged,app):
    import time
    sid=app.state.index.create('claude')['id']
    headers={'origin':'http://testserver'}
    with logged.websocket_connect(f'/ws/sessions/{sid}',headers=headers) as ws:
        ws.send_json({'type':'resume','seq':0})
        assert ws.receive_json()['type']=='snapshot'
        ws.send_json({'type':'send','client_id':'c','text':'hello','attachments':[]})
        assert ws.receive_json()['item']['kind']=='user'
    runtime=app.state.manager.get_or_create(sid)
    deadline=time.monotonic()+2
    while runtime.state!='running' and time.monotonic()<deadline: time.sleep(.01)
    assert runtime.state=='running'
    logged.portal.call(app.state.manager.stop,sid)
