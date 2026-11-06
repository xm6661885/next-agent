import asyncio, json, pathlib, tempfile
from types import SimpleNamespace
from server.more_agents.config import AcpAgent, CodexAgent, MoreAgentsConfig
from server.more_agents.items import Items
from server.more_agents.kinds.codex.process import CodexProcess


def test_config_discriminates_kinds():
    config=MoreAgentsConfig(agents=[{'kind':'acp','id':'a','name':'A','host':'localhost','port':1},
                                    {'kind':'codex','id':'c','name':'C'}])
    assert isinstance(config.agents[0], AcpAgent)
    assert isinstance(config.agents[1], CodexAgent)


def test_acp_items_use_tool_kind():
    events=[]; items=Items([],events.append)
    items.consume({'sessionUpdate':'tool_call','toolCallId':'t','title':'Read','kind':'read','rawInput':{'path':'x'},'status':'in_progress'})
    assert items.items[0]['tool_kind']=='read'


def test_fake_codex_process_round_trip():
    async def run():
        script=pathlib.Path(__file__).parent/'fixtures'/'fake_codex_app_server.py'
        agent=SimpleNamespace(command=str(script),args=[],env={})
        events=[]
        async def notify(method,params): events.append(method)
        async def request(method,params): return {}
        process=CodexProcess(agent,notify,request,'test')
        await process.start()
        result=await process.request('model/list',{'includeHidden':False})
        assert result['data'][0]['id']=='fake'
        await process.close()
        assert '__exit__' in events
    asyncio.run(run())
