from claude_agent_sdk import UserMessage, SystemMessage
from server.items import ItemBuilder, task_notification

NOTE = '<task-notification>\n<task-id>t1</task-id>\n<tool-use-id>tu</tool-use-id>\n<status>completed</status>\n<summary>Agent "x" completed</summary>\n</task-notification>'

def test_parse():
    assert task_notification(NOTE) == {'task_id':'t1','tool_use_id':'tu','status':'completed','summary':'Agent "x" completed'}
    assert task_notification('hello') is None

def test_user_turn_becomes_notice_once():
    b = ItemBuilder()
    b.consume(SystemMessage(subtype='task_notification',data={'task_id':'t1','status':'completed','summary':'done'}))
    out = b.consume(UserMessage(content=NOTE))
    notes = [x for x in b.items if x['kind']=='notice']
    assert len(notes)==1 and notes[0]['task']['task_id']=='t1' and out==[]
    assert not any(x['kind']=='user' for x in b.items)

def test_user_turn_alone():
    b = ItemBuilder()
    out = b.consume(UserMessage(content=NOTE))
    assert out[0]['item']['text']=='Background task finished: Agent "x" completed' and out[0]['item']['level']=='info'
