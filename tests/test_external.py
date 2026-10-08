import asyncio
import pytest
from conftest import FakeClaudeSDKClient
from test_runtime import until, result

def test_external_auth(client):
    assert client.get('/api/external/send',params={'prompt':'hi','agent_id':'claude','key':'x'}).status_code==403
    client.post('/api/login',json={'password':'070827'})
    assert client.patch('/api/config',json={'server':{'api_key':'secret'}}).status_code==200
    client.cookies.clear()
    assert client.get('/api/external/send',params={'prompt':'hi','agent_id':'claude','key':'bad'}).status_code==401
    assert client.get('/api/external/send',params={'prompt':'hi','agent_id':'nope','key':'secret'}).status_code==404
    r=client.get('/api/external/send',params={'prompt':'hi','agent_id':'claude','key':'secret'})
    assert r.status_code==200 and r.text=='Message Sent' and r.headers['x-session-id']

@pytest.mark.asyncio
async def test_external_strictly_serial(app):
    manager=app.state.manager
    s1=manager.external_send('claude','one')
    s2=manager.external_send('claude','two')
    assert s1!=s2
    await until(lambda:len(FakeClaudeSDKClient.instances)==1 and FakeClaudeSDKClient.instances[0].queries)
    await asyncio.sleep(.1)
    assert len(FakeClaudeSDKClient.instances)==1   # second waits for first turn
    FakeClaudeSDKClient.instances[0].push(result(s1,.1))
    await until(lambda:len(FakeClaudeSDKClient.instances)==2 and FakeClaudeSDKClient.instances[1].queries)
    assert manager.runtimes[s2].session['title']=='two'
    FakeClaudeSDKClient.instances[1].push(result(s2,.1))
    await until(lambda:manager.runtimes[s2].state=='idle')
    await manager.shutdown()
