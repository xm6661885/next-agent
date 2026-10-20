from claude_agent_sdk.types import AssistantMessage, ToolUseBlock, UserMessage, ToolResultBlock
from server.items import ItemBuilder

def test_late_assistant_copy_keeps_tool_result():
    b=ItemBuilder()
    use=ToolUseBlock(id='t1',name='Bash',input={'command':'x'})
    b.consume(AssistantMessage(content=[use],model='m',message_id='m1'))
    b.consume(UserMessage(content=[ToolResultBlock(tool_use_id='t1',content='ok')]))
    b.consume(AssistantMessage(content=[use],model='m',message_id='m1'))
    assert b.find('t1')['result']['content']=='ok'

def test_tool_result_patch_has_duration():
    b=ItemBuilder()
    b.consume(AssistantMessage(content=[ToolUseBlock(id='t2',name='Bash',input={})],model='m',message_id='m2'))
    out=b.consume(UserMessage(content=[ToolResultBlock(tool_use_id='t2',content='ok')]))
    assert isinstance(out[0]['patch']['duration_ms'],int)
    assert 't2' not in b.started


def test_image_meta_turn_is_synthetic():
    from server.items import is_synthetic_user
    assert is_synthetic_user([{'type':'text','text':'[Image: source: /tmp/x/1.png, original 10x10]'},{'type':'image','source':{}}])
    assert is_synthetic_user('[Image: source: /tmp/x/1.png]')
    assert not is_synthetic_user('look at [Image: source: x]')
