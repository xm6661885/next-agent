"""Deterministic stdio trace: no CLI configuration, network or model calls."""
import json
import os
import sys

threads, active, requests = {}, {}, {}
serial = 0

def send(message):
    print(json.dumps({'jsonrpc':'2.0', **message}), flush=True)

def event(method, tid, **params): send(dict(method=method, params=dict(threadId=tid, **params)))
def reply(rid, result): send(dict(id=rid, result=result))
def finish(tid, status='completed'):
    event('turn/completed', tid, turn=dict(id=active[tid]['id'], status=status, error={'message':'Turn failed'} if status=='failed' else None, durationMs=12))
    del active[tid]

def trace(tid):
    turn_id = active[tid]['id']
    def item(typ, iid, **fields):
        value = dict(type=typ, id=iid, **fields)
        event('item/started', tid, turnId=turn_id, item=value)
        return value
    item('userMessage','user',content=[])
    reasoning = item('reasoning','reason',summary=[],content=[])
    event('item/reasoning/summaryTextDelta', tid, turnId=turn_id, itemId='reason',summaryIndex=0,delta='Think')
    event('item/reasoning/summaryTextDelta', tid, turnId=turn_id, itemId='reason',summaryIndex=1,delta='Next')
    event('item/completed', tid, turnId=turn_id,item={**reasoning,'summary':['Think','Next']})
    command=item('commandExecution','cmd',command='printf ok',cwd=threads[tid]['cwd'],status='inProgress',aggregatedOutput=None,exitCode=None,durationMs=None)
    event('item/commandExecution/outputDelta',tid,turnId=turn_id,itemId='cmd',delta='ok')
    event('item/completed',tid,turnId=turn_id,item={**command,'status':'completed','aggregatedOutput':'ok\n','exitCode':0,'durationMs':2})
    changes=[dict(path='/workspace/a',kind=dict(type='update',move_path=None),diff='@@\n-old\n+new')]
    patch=item('fileChange','patch',changes=changes,status='inProgress')
    changes=[{**changes[0],'diff':'@@\n-old\n+latest'}]
    event('item/fileChange/patchUpdated',tid,turnId=turn_id,itemId='patch',changes=changes)
    event('item/completed',tid,turnId=turn_id,item={**patch,'status':'completed','changes':changes})
    tool=item('mcpToolCall','mcp',server='docs',tool='read',arguments={'key':'x'},status='inProgress',result=None)
    event('item/completed',tid,turnId=turn_id,item={**tool,'status':'completed','result':{'content':[{'type':'text','text':'doc'},{'type':'text','text':'more'}],'isError':False}})
    item('webSearch','web',query='search',action={'type':'openPage','url':'https://example.com'})
    item('futureTool','unknown',payload='kept')
    event('turn/plan/updated',tid,turnId=turn_id,plan=[dict(step='Implement',status='inProgress')],explanation='First')
    event('turn/plan/updated',tid,turnId=turn_id,plan=[dict(step='Implement',status='completed')],explanation='Done')
    for iid,phase,delta,final in [('comment','commentary','Working','Working.'),('final','final_answer','o','ok')]:
        message=item('agentMessage',iid,text='',phase=phase)
        event('item/agentMessage/delta',tid,turnId=turn_id,itemId=iid,delta=delta)
        event('item/completed',tid,turnId=turn_id,item={**message,'text':final})
    threads[tid]['turns'] += 1
    n=threads[tid]['turns']
    event('thread/tokenUsage/updated',tid,tokenUsage=dict(total=dict(inputTokens=10*n,cachedInputTokens=2*n,outputTokens=4*n,reasoningOutputTokens=n,totalTokens=14*n),last={'totalTokens':14},modelContextWindow=1000))

for line in sys.stdin:
    message=json.loads(line)
    if os.environ.get('FAKE_LOG'):
        with open(os.environ['FAKE_LOG'],'a') as log: log.write(json.dumps(message)+'\n')
    method=message.get('method'); rid=message.get('id'); p=message.get('params') or {}
    if method=='initialize': reply(rid, {'userAgent':'fake'})
    elif method=='initialized': pass
    elif method=='model/list':
        models=[dict(id='fake',model='fake',displayName='Fake',description='Test model',supportedReasoningEfforts=[dict(reasoningEffort=e,description=e) for e in ('low','high')],defaultReasoningEffort='low'),
                dict(id='other',model='other',displayName='Other',description='Other model',supportedReasoningEfforts=[dict(reasoningEffort='medium',description='Medium')],defaultReasoningEffort='medium')]
        reply(rid,dict(data=models,nextCursor=None))
    elif method in ('thread/start','thread/resume'):
        if p.get('threadId')=='missing':
            send(dict(id=rid,error=dict(code=-32600,message='no rollout found for thread missing'))); continue
        serial+=1
        tid=p.get('threadId') or 'thread-'+str(os.getpid())+'-'+str(serial)
        threads[tid]=dict(cwd=p['cwd'],turns=0)
        reply(rid,dict(thread={'id':tid},model=p.get('model','fake'),reasoningEffort=p['config'].get('model_reasoning_effort','low')))
    elif method=='thread/unsubscribe': reply(rid, {'status':'unsubscribed'})
    elif method=='turn/start':
        tid=p['threadId']; serial+=1
        prompt=next((i['text'] for i in p['input'] if i['type']=='text'),'')
        active[tid]=dict(id='turn-'+str(serial),prompt=prompt)
        reply(rid,dict(turn=dict(id=active[tid]['id'],status='inProgress')))
        event('turn/started',tid,turn=dict(id=active[tid]['id'],status='inProgress'))
        if prompt=='exit': sys.exit(3)
        if prompt in ('hold','race'): continue
        if prompt in ('approve','file-approve','profile','question','unsupported','resolved'):
            server_id='approval-'+str(serial); requests[server_id]=tid
            params=dict(threadId=tid,turnId=active[tid]['id'],itemId='cmd')
            if prompt in ('approve','resolved'):
                method='item/commandExecution/requestApproval'; params.update(command='touch x',cwd=threads[tid]['cwd'],availableDecisions=['accept','acceptForSession','decline'])
            elif prompt=='file-approve': method='item/fileChange/requestApproval'
            elif prompt=='profile': method='item/permissions/requestApproval'; params.update(permissions={'network':{'enabled':True}})
            elif prompt=='question':
                method='item/tool/requestUserInput';params['questions']=[dict(id='q',header='Pick',question='Which?',isOther=True,isSecret=False,options=[dict(label='One',description='First')])]
            else: method='unsupported/test'
            send(dict(id=server_id,method=method,params=params))
            continue
        if prompt=='fail': finish(tid,'failed'); continue
        trace(tid);finish(tid)
    elif method=='turn/steer':
        tid=p['threadId']
        if active[tid]['prompt']=='race':
            finish(tid);send(dict(id=rid,error=dict(code=-32600,message='no active turn')))
        else:
            reply(rid,dict(turnId=active[tid]['id']))
            trace(tid);finish(tid)
    elif method=='test/resolve':
        tid=p['threadId']
        for req,thread in list(requests.items()):
            if thread==tid:
                event('serverRequest/resolved',tid,requestId=req);del requests[req]
        finish(tid);reply(rid,{})
    elif method=='turn/interrupt':
        tid=p['threadId']; reply(rid,{})
        for req, thread in list(requests.items()):
            if thread==tid:
                event('serverRequest/resolved',tid,requestId=req)
                del requests[req]
        if tid in active: finish(tid,'interrupted')
    elif method is None and rid in requests:
        tid=requests.pop(rid)
        if tid in active: trace(tid); finish(tid)
    else: send(dict(id=rid,error=dict(code=-32601,message='Method not found')))
