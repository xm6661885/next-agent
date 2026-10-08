import pytest
from claude_agent_sdk import SystemMessage, StreamEvent, ResultMessage
from server.items import ItemBuilder

def system(subtype,**data):
    return SystemMessage(subtype=subtype,data=data)

def test_activity_status_retry_thinking_and_clear(monkeypatch):
    import server.items
    clock=[10.0]
    monkeypatch.setattr(server.items.time,'monotonic',lambda:clock[0])
    builder=ItemBuilder()
    assert builder.consume(system('status',status='requesting'))[0]['activity']['kind']=='requesting'
    assert builder.consume(system('status',status=None))==[]
    assert builder.consume(system('api_retry',attempt=2,max_retries=10,retry_delay_ms=4000,
                                  error_status=529,error='overloaded',no_response={'waited_ms':60000}))[0]['activity']['no_response']['waited_ms']==60000
    assert builder.consume(system('thinking_tokens',estimated_tokens=100))[0]['activity']['estimated_tokens']==100
    clock[0]=10.5
    assert builder.consume(system('thinking_tokens',estimated_tokens=200))==[]
    clock[0]=11.1
    assert builder.consume(system('thinking_tokens',estimated_tokens=300))[0]['activity']['estimated_tokens']==300
    assert builder.consume(StreamEvent(uuid='s',session_id='s',event={'type':'message_start','message':{'id':'m'}}))[0]=={'type':'activity','activity':None}
    assert builder.consume(system('status',status='compacting'))[0]['activity']['kind']=='compacting'
    assert builder.consume(system('status',status='idle'))==[{'type':'activity','activity':None}]
    builder.consume(system('status',status='requesting'))
    result=ResultMessage(subtype='success',duration_ms=1,duration_api_ms=1,is_error=False,num_turns=1,session_id='s')
    assert builder.consume(result)[0]=={'type':'activity','activity':None}

@pytest.mark.asyncio
async def test_snapshot_and_disconnect_clear(app):
    sid=app.state.index.create('claude')['id']
    runtime=app.state.manager.get_or_create(sid)
    runtime.items.set_activity({'kind':'requesting','at':'now'})
    assert (await runtime.snapshot())['activity']['kind']=='requesting'
    await runtime._disconnect()
    assert runtime.items.activity is None
    assert any(e['type']=='activity' and e['activity'] is None for e in runtime.ring)

def test_split_assistant_messages_match_streamed_blocks():
    from claude_agent_sdk import AssistantMessage, TextBlock, ThinkingBlock, ToolUseBlock
    from server.items import ItemBuilder
    b=ItemBuilder()
    ev=lambda e: b.consume(StreamEvent(uuid='s',session_id='s',event=e))
    ev({'type':'message_start','message':{'id':'m'}})
    blocks=[{'type':'thinking','thinking':''},{'type':'text','text':''},{'type':'tool_use','id':'t1','name':'Bash'}]
    for i,blk in enumerate(blocks): ev({'type':'content_block_start','index':i,'content_block':blk})
    ev({'type':'content_block_delta','index':2,'delta':{'type':'input_json_delta','partial_json':'{"command":"ls"}'}})
    b.consume(AssistantMessage(content=[ThinkingBlock('hm','sig')],model='o',message_id='m'))
    b.consume(AssistantMessage(content=[TextBlock('hi')],model='o',message_id='m'))
    b.consume(AssistantMessage(content=[ToolUseBlock(id='t1',name='Bash',input={'command':'ls'})],model='o',message_id='m'))
    for i in range(3): ev({'type':'content_block_stop','index':i})
    items=list(b.items)
    assert [x['kind'] for x in items]==['thinking','text','tool']
    assert items[0]['text']=='hm' and items[1]['text']=='hi' and items[2]['input']=={'command':'ls'}
