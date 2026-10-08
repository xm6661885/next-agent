from claude_agent_sdk.types import SessionMessage
from server.history import load_items, transcript_parent
from server.config import Agent

def test_conversion_attachment(tmp_path,monkeypatch):
    path=str(tmp_path/'file.txt')
    messages=[SessionMessage(type='user',uuid='u1',session_id='s',message={'content':[{'type':'text','text':'Hello\nThe user sent a file: '+path}]}),
              SessionMessage(type='assistant',uuid='a1',session_id='s',message={'content':[{'type':'tool_use','id':'tool1','name':'Read','input':{}},{'type':'text','text':'Done'}]}),
              SessionMessage(type='user',uuid='u2',session_id='s',message={'content':[{'type':'tool_result','tool_use_id':'tool1','content':'ok'}]})]
    monkeypatch.setattr('server.history.get_session_messages',lambda *a,**k:messages)
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
    from claude_agent_sdk._internal.message_parser import parse_message
    from server.items import ItemBuilder
    data={'type':'user','uuid':'u1','isSynthetic':True,'isReplay':True,
          'message':{'role':'user','content':[{'type':'text','text':'Base directory for this skill: /x'}]}}
    builder=ItemBuilder()
    assert builder.consume(parse_message(data))==[]
    data.pop('isSynthetic')
    assert any(e.get('item',{}).get('kind')=='user' for e in builder.consume(parse_message(data)))
