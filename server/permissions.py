"""Pending interactive SDK permission requests."""
import asyncio
from dataclasses import dataclass
from uuid import uuid4
from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny, PermissionUpdate, PermissionRuleValue
from .config import now

@dataclass
class PendingPermission:
    request: dict
    future: asyncio.Future
    context: object
    tool_name: str
    input: dict
    mode: str | None = None

class PermissionRegistry:
    def __init__(self, runtime):
        self.runtime = runtime
        self.pending = {}

    def make_can_use_tool(self):
        async def can_use_tool(tool_name, input, ctx):
            kind = 'question' if tool_name=='AskUserQuestion' else 'plan' if tool_name=='ExitPlanMode' else 'tool'
            pid = 'perm-'+uuid4().hex
            request = dict(id=pid,session_id=self.runtime.sid,kind=kind,tool_name=tool_name,
                           tool_use_id=ctx.tool_use_id,input=input,title=ctx.title or ctx.display_name or tool_name,
                           description=ctx.description or '',decision_reason=ctx.decision_reason or '',
                           blocked_path=ctx.blocked_path,suggestions=[s.to_dict() for s in ctx.suggestions],created_at=now())
            future = asyncio.get_running_loop().create_future()
            pending = PendingPermission(request,future,ctx,tool_name,input)
            self.pending[pid] = pending
            self.runtime.emit({'type':'permission','request':request})
            self.runtime.manager.session_state(self.runtime)
            await self.runtime.manager.extensions.emit('permission_request',session_id=self.runtime.sid,
                                                        agent_id=self.runtime.session['agent_id'],request=request)
            result = await future
            if pending.mode:
                asyncio.get_running_loop().call_soon(self.runtime.commands.put_nowait, ('set_mode', pending.mode))
            return result
        return can_use_tool

    def reply(self, pid,decision,message='',answers=None,mode=None):
        pending = self.pending.pop(pid,None)
        if not pending: return False
        kind = pending.request['kind']
        if decision in ('allow','allow_always'):
            if kind=='question':
                result = PermissionResultAllow(updated_input={'questions':pending.input.get('questions',[]),'answers':answers or {}})
            elif kind=='plan':
                result = PermissionResultAllow()
                if mode:
                    self.runtime.persist_override('permission_mode',mode)
                    pending.mode=mode
            elif decision=='allow_always':
                updates = pending.context.suggestions or [PermissionUpdate(type='addRules',
                    rules=[PermissionRuleValue(tool_name=pending.tool_name)],behavior='allow',destination='session')]
                result = PermissionResultAllow(updated_permissions=updates)
            else: result = PermissionResultAllow()
        else:
            default = {'tool':'The user denied this action.','question':'The user declined to answer.',
                       'plan':'The user rejected the plan. Ask what to change.'}[kind]
            result = PermissionResultDeny(message=message or default)
        pending.future.set_result(result)
        self.runtime.emit({'type':'permission_resolved','id':pid,'decision':'allow' if decision.startswith('allow') else 'deny'})
        self.runtime.manager.session_state(self.runtime)
        return True

    def cancel_all(self):
        for pid,pending in list(self.pending.items()):
            self.pending.pop(pid,None)
            if not pending.future.done(): pending.future.set_result(PermissionResultDeny(message='Cancelled.',interrupt=True))
            self.runtime.emit({'type':'permission_resolved','id':pid,'decision':'cancelled'})
        self.runtime.manager.session_state(self.runtime)
