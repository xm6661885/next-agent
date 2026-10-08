"""WebSocket command and event handlers."""
import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from .history import page

async def session_socket(ws: WebSocket, sid, auth, manager, index, uploads):
    if not await auth.require_ws(ws): return
    if sid not in index.sessions:
        await ws.accept()
        await ws.close(code=4404)
        return
    await ws.accept()
    runtime=manager.get_or_create(sid)
    queue=asyncio.Queue(maxsize=1000)
    runtime.subscribers.add(queue)
    try:
        first=await ws.receive_json()
        if first.get('type')!='resume':
            await ws.send_json({'type':'error','message':'First message must be resume'})
            return
        seq=first.get('seq') or 0
        ring=list(runtime.ring)
        if seq and (not ring or seq>=ring[0]['seq']-1 and seq<=runtime.seq):
            for event in ring:
                if event['seq']>seq: await ws.send_json(event)
            baseline=ring[-1]['seq'] if ring else seq
        else:
            snapshot=await runtime.snapshot()
            await ws.send_json(snapshot)
            baseline=snapshot['seq']
        buffered=[]
        while not queue.empty():
            event=queue.get_nowait()
            if event.get('seq',0)>baseline: buffered.append(event)
        for event in buffered: queue.put_nowait(event)
        async def sender():
            while True:
                event=await queue.get()
                if event.get('type')=='__overflow__':
                    await ws.close(code=1013)
                    return
                await ws.send_json(event)
        send_task=asyncio.create_task(sender())
        try:
            while True:
                msg=await ws.receive_json()
                typ=msg.get('type')
                req_id=msg.get('req_id')
                try:
                    if typ=='resume':
                        seq=msg.get('seq') or 0
                        ring=list(runtime.ring)
                        if seq and ring and seq>=ring[0]['seq']-1 and seq<=runtime.seq:
                            for event in ring:
                                if event['seq']>seq: await ws.send_json(event)
                        else: await ws.send_json(await runtime.snapshot())
                    elif typ=='send':
                        attachments=[uploads.get(sid,fid) for fid in msg.get('attachments',[])]
                        content=uploads.build_content(msg.get('text',''),attachments)
                        if not content: raise ValueError('Message is empty')
                        if not runtime.session['title']:
                            runtime.session['title']=(msg.get('text') or attachments[0]['name'])[:60]
                            index.update(sid,title=runtime.session['title'])
                            manager.session_state(runtime)
                        runtime.emit(runtime.items.pending_user(msg.get('text',''),
                                     [{k:a[k] for k in ('id','name','mime','size','path','url','is_image')} for a in attachments],
                                     msg.get('client_id')))
                        runtime.submit(('send',{'content':content},req_id,queue))
                    elif typ=='edit':
                        uuid=msg.get('uuid')
                        if not isinstance(uuid,str) or not uuid.strip(): raise ValueError('uuid is required')
                        attachments=[uploads.get(sid,fid) for fid in msg.get('attachments',[])]
                        content=uploads.build_content(msg.get('text',''),attachments)
                        if not content: raise ValueError('Message is empty')
                        runtime.submit(('edit',{'uuid':uuid,'content':content,'text':msg.get('text',''),
                                                'attachments':[{k:a[k] for k in ('id','name','mime','size','path','url','is_image')} for a in attachments],
                                                'client_id':msg.get('client_id'),'rewind_files':bool(msg.get('rewind_files'))},req_id,queue))
                    elif typ in ('interrupt','set_mode','set_model','set_effort','stop_task','rewind'):
                        field={'set_mode':'mode','set_model':'model','set_effort':'effort','stop_task':'task_id','rewind':'uuid'}.get(typ)
                        if field and field not in msg: raise ValueError(f'{field} is required')
                        runtime.submit((typ,msg[field],req_id,queue) if field else (typ,None,req_id,queue))
                    elif typ=='permission_reply':
                        if not runtime.permissions.reply(msg.get('id'),msg.get('decision','deny'),
                                                         msg.get('message',''),msg.get('answers'),msg.get('mode')):
                            raise ValueError('Permission request is not pending')
                    elif typ=='ping': await ws.send_json({'type':'pong','seq':runtime.seq})
                    else: raise ValueError('Unknown command')
                except Exception as exc:
                    await ws.send_json({'type':'error','req_id':req_id,'message':str(exc),'seq':runtime.seq})
        finally:
            send_task.cancel()
    except WebSocketDisconnect:
        pass
    finally:
        runtime.subscribers.discard(queue)

async def events_socket(ws: WebSocket, auth, manager, agents):
    if not await auth.require_ws(ws): return
    await ws.accept()
    queue=asyncio.Queue(maxsize=1000)
    manager.global_subscribers.add(queue)
    try:
        await ws.send_json({'type':'hello','agents':[{'id':a['id'],'status':a['status']} for a in agents.list()],
                            'sessions':[{'id':s['id'],'agent_id':s['agent_id'],'state':manager.view(s['id'])['state'],
                                         'pending':manager.view(s['id'])['pending']} for s in manager.index.sessions.values()]})
        while True:
            event_task=asyncio.create_task(queue.get())
            close_task=asyncio.create_task(ws.receive())
            done,pending=await asyncio.wait({event_task,close_task},return_when=asyncio.FIRST_COMPLETED)
            for task in pending: task.cancel()
            if close_task in done:
                message=close_task.result()
                if message['type']=='websocket.disconnect': break
            if event_task in done:
                event=event_task.result()
                if event.get('type')=='__overflow__':
                    await ws.close(code=1013)
                    break
                await ws.send_json(event)
    except WebSocketDisconnect:
        pass
    finally: manager.global_subscribers.discard(queue)
