import asyncio
import pytest
from fastapi.testclient import TestClient
from claude_agent_sdk import UserMessage
import os
os.environ.setdefault("NEXT_AGENT_PASSWORD", "070827")
from server.app import create_app

class FakeClaudeSDKClient:
    instances=[]
    def __init__(self,options):
        self.options=options; self.messages=asyncio.Queue(); self.connected=False; self.queries=[]
        self.mode=None; self.model=None; self.interrupted=False; self.stopped=[]; self.rewound=[]
        self.instances.append(self)
    async def connect(self): self.connected=True
    async def disconnect(self): self.connected=False; self.messages.put_nowait(None)
    async def receive_messages(self):
        while True:
            msg=await self.messages.get()
            if msg is None: return
            if isinstance(msg,Exception): raise msg
            yield msg
    async def query(self,prompt,session_id='default'):
        async for msg in prompt: self.queries.append(msg)
        self.messages.put_nowait(UserMessage(content=self.queries[-1]['message']['content'],uuid='echo-'+str(len(self.queries))))
    async def interrupt(self): self.interrupted=True
    async def set_permission_mode(self,mode): self.mode=mode
    async def set_model(self,model): self.model=model
    async def get_context_usage(self): return {'totalTokens':100,'maxTokens':1000,'percentage':10}
    async def stop_task(self,task_id): self.stopped.append(task_id)
    async def rewind_files(self,uuid): self.rewound.append(uuid)
    def push(self,msg): self.messages.put_nowait(msg)

@pytest.fixture
def app(tmp_path,monkeypatch):
    import server.runtime
    FakeClaudeSDKClient.instances.clear()
    monkeypatch.setattr(server.runtime,'ClaudeSDKClient',FakeClaudeSDKClient)
    return create_app(tmp_path)

@pytest.fixture
def client(app):
    with TestClient(app,base_url='http://testserver') as c: yield c

@pytest.fixture
def logged(client):
    assert client.post('/api/login',json={'password':'070827'}).status_code==200
    return client
