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
