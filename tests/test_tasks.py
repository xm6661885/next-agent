from claude_agent_sdk import SystemMessage, AssistantMessage, UserMessage, ToolUseBlock, ToolResultBlock
from server.items import ItemBuilder

def sysmsg(subtype, **data):
    return SystemMessage(subtype=subtype, data={'subtype':subtype, **data})

def test_subagent_task_lifecycle():
    b = ItemBuilder()
    b.consume(sysmsg('task_started', task_id='t1', tool_use_id='tu1', description='Explore', task_type='local_agent'))
    b.consume(sysmsg('task_progress', task_id='t1', description='Explore', last_tool_name='Grep',
                     usage={'total_tokens':10,'tool_uses':2,'duration_ms':500}))
    t = b.tasks['t1']
    assert t['status']=='running' and t['last_tool_name']=='Grep' and t['usage']['tool_uses']==2
    out = b.consume(sysmsg('task_updated', task_id='t1', patch={'status':'killed'}))
    assert out[0]['tasks'][0]['status']=='stopped'

def test_cron_mirrored_from_tool_calls():
    b = ItemBuilder()
    b.consume(AssistantMessage(content=[ToolUseBlock(id='c1',name='CronCreate',input={'cron':'*/5 * * * *','prompt':'check'})],model='m'))
    b.consume(UserMessage(content=[ToolResultBlock(tool_use_id='c1',content='Scheduled recurring job abc123 (every 5 minutes). Ok. Auto-expires after 7 days.')]))
    assert b.tasks['cron:abc123']['cron']=='*/5 * * * *'
    b.consume(AssistantMessage(content=[ToolUseBlock(id='c2',name='CronDelete',input={'id':'abc123'})],model='m'))
    b.consume(UserMessage(content=[ToolResultBlock(tool_use_id='c2',content='ok')]))
    assert 'cron:abc123' not in b.tasks

def test_cron_one_shot_id():
    b = ItemBuilder()
    b.consume(AssistantMessage(content=[ToolUseBlock(id='c1',name='CronCreate',input={'cron':'1 2 3 4 *','prompt':'x','recurring':False})],model='m'))
    b.consume(UserMessage(content=[ToolResultBlock(tool_use_id='c1',content='Scheduled one-shot task f00d (Apr 3 02:01). x. It will fire once then auto-delete.')]))
    assert b.tasks['cron:f00d']['schedule']=='Apr 3 02:01' and not b.tasks['cron:f00d']['recurring']
