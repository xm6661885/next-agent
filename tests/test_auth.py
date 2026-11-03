import bcrypt
from starlette.websockets import WebSocketDisconnect

def test_login_rotation(client,app):
    assert client.get('/api/agents').status_code==401
    assert client.post('/api/login',json={'password':'bad'}).status_code==401
    assert client.post('/api/login',json={'password':'070827'}).status_code==200
    old=client.cookies.get('na_auth')
    assert client.get('/api/me').status_code==200
    app.state.config.core_doc['server']['password_hash']=bcrypt.hashpw(b'new',bcrypt.gensalt()).decode()
    app.state.config.save()
    assert client.get('/api/me').status_code==401
    assert client.post('/api/login',json={'password':'new'}).status_code==200
    assert client.cookies.get('na_auth')!=old

def test_rate_limit(client):
    for _ in range(9): assert client.post('/api/login',json={'password':'bad'}).status_code==401
    assert client.post('/api/login',json={'password':'bad'}).status_code==429

def test_ws_auth(client):
    try:
        with client.websocket_connect('/ws/events',headers={'origin':'http://testserver'}): pass
    except WebSocketDisconnect as exc: assert exc.code==4401
    client.post('/api/login',json={'password':'070827'})
    try:
        with client.websocket_connect('/ws/events',headers={'origin':'http://evil.example'}): pass
    except WebSocketDisconnect as exc: assert exc.code==4403

def test_set_password_writes_core_only(app,monkeypatch):
    import server.__main__ as cli
    paths=app.state.paths
    before=paths.agents_config.read_bytes()
    monkeypatch.setattr(cli,'DataDir',lambda:paths)
    monkeypatch.setattr(cli.getpass,'getpass',lambda prompt:'new password')
    monkeypatch.setattr('sys.argv',['server','set-password'])
    cli.main()
    app.state.config.load()
    assert bcrypt.checkpw(b'new password',app.state.config.config.server.password_hash.encode())
    assert paths.agents_config.read_bytes()==before and not paths.config.exists()
