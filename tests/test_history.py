from server.transcript import Message
from server.history import load_items, transcript_parent
from server.config import Agent

def test_conversion_attachment(tmp_path,monkeypatch):
    path=str(tmp_path/'file.txt')
    messages=[Message(type='user',uuid='u1',message={'content':[{'type':'text','text':'Hello\nThe user sent a file: '+path}]}),
              Message(type='assistant',uuid='a1',message={'content':[{'type':'tool_use','id':'tool1','name':'Read','input':{}},{'type':'text','text':'Done'}]}),
              Message(type='user',uuid='u2',message={'content':[{'type':'tool_result','tool_use_id':'tool1','content':'ok'}]})]
    monkeypatch.setattr('server.history.session_messages',lambda *a,**k:messages)
    attachment={'id':'f','name':'file.txt','mime':'text/plain','size':1,'path':path,'url':'/api/uploads/s/f','is_image':False}
    items=load_items({'id':'s','sdk_session_id':'s'},Agent(id='a',name='A',cwd=str(tmp_path)),{'f':attachment})
    assert items[0]['text']=='Hello' and items[0]['attachments']==[attachment]
    assert items[1]['result']['content']=='ok' and items[2]['text']=='Done'

def test_transcript_parent_skips_bad_lines(tmp_path,monkeypatch):
    import server.history
    path=tmp_path/'session.jsonl'
    path.write_text('bad json\n{"uuid":"u1","parentUuid":null}\n{"uuid":"u2","parentUuid":"parent"}\n')
    monkeypatch.setattr(server.history,'transcript_path',lambda *a:path)
    assert transcript_parent('s',str(tmp_path),'u2')=='parent'
    assert transcript_parent('s',str(tmp_path),'u1') is None

def test_synthetic_skill_turn_hidden():
    from claude_agent_sdk import UserMessage, TextBlock
    from server.items import ItemBuilder
    builder=ItemBuilder()
    assert builder.consume(UserMessage(content=[TextBlock(text='Base directory for this skill: /x')],uuid='u1'))==[]
    assert any(e.get('item',{}).get('kind')=='user' for e in builder.consume(UserMessage(content=[TextBlock(text='hello')],uuid='u2')))

def test_compaction_keeps_earlier_messages(tmp_path,monkeypatch):
    import json, server.history
    lines=[{'type':'user','uuid':'u1','parentUuid':None,'sessionId':'s','message':{'role':'user','content':'before'}},
           {'type':'system','subtype':'compact_boundary','uuid':'b','parentUuid':None,'logicalParentUuid':'u1','sessionId':'s'},
           {'type':'user','uuid':'c','parentUuid':'b','sessionId':'s','isCompactSummary':True,'message':{'role':'user','content':'This session is being continued...'}},
           {'type':'user','uuid':'u2','parentUuid':'c','sessionId':'s','message':{'role':'user','content':'after'}}]
    path=tmp_path/'s.jsonl'; path.write_text('\n'.join(json.dumps(x) for x in lines))
    monkeypatch.setattr('server.transcript.transcript_path',lambda *a:path)
    items=load_items({'id':'s2','sdk_session_id':'s'},Agent(id='a',name='A',cwd=str(tmp_path)))
    assert [i.get('text') for i in items]==['before','Context compacted','after']
