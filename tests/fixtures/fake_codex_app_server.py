#!/usr/bin/env python3
"""Tiny deterministic Codex app-server used by More Agents tests."""
import json, sys, uuid

def send(message):
    sys.stdout.write(json.dumps(message,separators=(',',':'))+'\n'); sys.stdout.flush()

def main():
    thread='thread-'+uuid.uuid4().hex[:8]; active=None; initialized=False
    for line in sys.stdin:
        request=json.loads(line); method=request.get('method'); rid=request.get('id'); p=request.get('params') or {}
        if method=='initialize':
            initialized=True; send({'jsonrpc':'2.0','id':rid,'result':{'serverInfo':{'name':'fake-codex','version':'0'},'capabilities':{}}})
        elif method=='model/list': send({'jsonrpc':'2.0','id':rid,'result':{'data':[{'id':'fake','name':'Fake','supportedReasoningEfforts':['low','high'],'defaultReasoningEffort':'low'}]}})
        elif method in ('thread/start','thread/resume'):
            thread=p.get('threadId',thread); send({'jsonrpc':'2.0','id':rid,'result':{'thread':{'id':thread},'model':'fake','reasoningEffort':'low'}})
        elif method=='turn/start':
            active='turn-'+uuid.uuid4().hex[:8]; send({'jsonrpc':'2.0','id':rid,'result':{'turn':{'id':active,'status':'inProgress'}}})
            send({'jsonrpc':'2.0','method':'turn/started','params':{'threadId':thread,'turn':{'id':active,'status':'inProgress'}}})
            item='message-'+uuid.uuid4().hex[:8]
            send({'jsonrpc':'2.0','method':'item/started','params':{'threadId':thread,'turnId':active,'item':{'type':'agentMessage','id':item,'text':'','phase':'final_answer'}}})
            send({'jsonrpc':'2.0','method':'item/agentMessage/delta','params':{'threadId':thread,'turnId':active,'itemId':item,'delta':'ok'}})
            send({'jsonrpc':'2.0','method':'item/completed','params':{'threadId':thread,'turnId':active,'item':{'type':'agentMessage','id':item,'text':'ok','phase':'final_answer'}}})
            send({'jsonrpc':'2.0','method':'turn/completed','params':{'threadId':thread,'turn':{'id':active,'status':'completed'}}})
        elif method=='turn/steer': send({'jsonrpc':'2.0','id':rid,'result':{'turnId':active}})
        elif method=='turn/interrupt':
            send({'jsonrpc':'2.0','id':rid,'result':{}}); send({'jsonrpc':'2.0','method':'turn/completed','params':{'threadId':thread,'turn':{'id':active,'status':'interrupted'}}})
        else: send({'jsonrpc':'2.0','id':rid,'result':{}})
if __name__=='__main__': main()
