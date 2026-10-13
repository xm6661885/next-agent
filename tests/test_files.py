from urllib.parse import quote
from server.items import item

def test_shared_files_access_and_headers(logged,app,tmp_path):
    sid=app.state.index.create('claude')['id']
    runtime=app.state.manager.get_or_create(sid)
    folder=tmp_path/'files'; folder.mkdir()
    image=folder/'a b.png'; image.write_bytes(b'PNG')
    html=folder/'page.html'; html.write_text('<script>bad()</script>')
    private=folder/'private.txt'; private.write_text('private')
    runtime.items.add(item('text',text=f'![image](file://{quote(str(image))}) [page](file://{html})',streaming=False))
    url=f'/api/sessions/{sid}/files'
    assert logged.get(url,params={'path':str(private)}).status_code==404
    assert logged.get(url,params={'path':'relative.png'}).status_code==404
    assert logged.get(url,params={'path':str(folder/'x'/'..'/'a b.png')}).content==b'PNG'
    assert logged.get(url,params={'path':str(image)}).content==b'PNG'
    stat=logged.get(url+'/stat',params={'path':str(image)}).json()
    assert stat=={'name':'a b.png','size':3,'mime':'image/png','is_image':True}
    response=logged.get(url,params={'path':str(html),'download':1})
    assert 'attachment' in response.headers['content-disposition']
    response=logged.get(url,params={'path':str(html)})
    assert response.headers['content-type'].startswith('text/plain')
    assert response.headers['x-content-type-options']=='nosniff'

def test_artifacts_and_tool_file_access(logged,app,tmp_path):
    sid=app.state.index.create('claude')['id']
    runtime=app.state.manager.get_or_create(sid)
    image=tmp_path/'chart a.png'; image.write_bytes(b'PNG')
    report=tmp_path/'report.pdf'; report.write_bytes(b'PDF')
    edit=tmp_path/'source.py'; edit.write_text('x')
    notebook=tmp_path/'work.ipynb'; notebook.write_text('{}')
    missing=tmp_path/'missing.txt'
    denied=tmp_path/'denied.txt'; denied.write_text('private')
    def stamp(value,ts): value['ts']=f'2026-01-01T00:00:{ts:02d}+00:00'; return value
    ok={'content':'ok','is_error':False,'images':[]}
    runtime.history_base=[
        stamp(item('user',text='',attachments=[{'path':str(image),'url':f'/api/uploads/{sid}/upload1'}]),1),
        stamp(item('text',text=f'![chart](file://{quote(str(image))})',streaming=False),2),
        stamp(item('tool',name='Write',input={'file_path':str(report)},result=ok),3),
        stamp(item('tool',name='Edit',input={'file_path':str(edit)},result=ok),4),
        stamp(item('tool',name='NotebookEdit',input={'notebook_path':str(notebook)},result=ok),5),
        stamp(item('tool',name='MultiEdit',input={'file_path':str(missing)},result=ok),6),
        stamp(item('tool',name='Write',input={'file_path':str(denied)},result={'is_error':True}),7),
        stamp(item('tool',name='Write',input={'file_path':str(denied)},result=None),8),
        stamp(item('tool',name='Read',input={'file_path':str(denied)},result=ok),9)]
    values=logged.get(f'/api/sessions/{sid}/artifacts').json()
    assert [a['path'] for a in values]==[str(missing),str(notebook),str(edit),str(report),str(image)]
    chart=values[-1]
    assert chart['sources']==['upload','link'] and chart['is_image'] and chart['size']==3
    assert chart['first_ts'].endswith('01+00:00') and chart['last_ts'].endswith('02+00:00')
    assert chart['url']==f'/api/uploads/{sid}/upload1'
    assert values[0]['exists'] is False and values[0]['size'] is None
    assert values[3]['mime']=='application/pdf' and values[3]['url'].startswith(f'/api/sessions/{sid}/files?path=')
    files=f'/api/sessions/{sid}/files'
    assert logged.get(files,params={'path':str(report)}).content==b'PDF'
    assert logged.get(files,params={'path':str(edit)}).status_code==200
    assert logged.get(files,params={'path':str(notebook)}).status_code==200
    assert logged.get(files,params={'path':str(denied)}).status_code==404
