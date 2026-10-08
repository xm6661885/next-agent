import asyncio
import pytest
from claude_agent_sdk.types import ToolPermissionContext, PermissionUpdate, PermissionResultAllow, PermissionResultDeny

@pytest.mark.asyncio
async def test_permission_mappings(app):
    sid=app.state.index.create('claude')['id']; runtime=app.state.manager.get_or_create(sid)
    callback=runtime.permissions.make_can_use_tool()
    async def ask(name,input,ctx=None):
        task=asyncio.create_task(callback(name,input,ctx or ToolPermissionContext(tool_use_id='tool1')))
        await asyncio.sleep(0)
        return task,next(iter(runtime.permissions.pending))
    task,pid=await ask('Bash',{}); runtime.permissions.reply(pid,'allow')
    assert isinstance(await task,PermissionResultAllow)
    task,pid=await ask('Bash',{}); runtime.permissions.reply(pid,'deny')
    assert isinstance(await task,PermissionResultDeny)
    task,pid=await ask('Bash',{}); runtime.permissions.reply(pid,'allow_always')
    assert (await task).updated_permissions[0].rules[0].tool_name=='Bash'
    suggestion=PermissionUpdate(type='addRules',destination='localSettings',behavior='allow')
    task,pid=await ask('Read',{},ToolPermissionContext(tool_use_id='tool2',suggestions=[suggestion]))
    runtime.permissions.reply(pid,'allow_always')
    assert (await task).updated_permissions==[suggestion]
    q={'questions':[{'question':'Which?'}]}
    task,pid=await ask('AskUserQuestion',q); runtime.permissions.reply(pid,'allow',answers={'Which?':'One'})
    assert (await task).updated_input=={'questions':q['questions'],'answers':{'Which?':'One'}}
    task,pid=await ask('ExitPlanMode',{'plan':'go'}); runtime.permissions.reply(pid,'allow',mode='acceptEdits')
    assert isinstance(await task,PermissionResultAllow)
    assert runtime.session['overrides']['permission_mode']=='acceptEdits'
    await asyncio.sleep(0)
    assert runtime.commands.get_nowait()==('set_mode','acceptEdits')
    task,pid=await ask('Bash',{}); runtime.permissions.cancel_all()
    assert (await task).interrupt
