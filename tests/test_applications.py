import pytest
from test_files import workspace
from app import applications


def test_application_crud_and_concurrent_edit(workspace):
    client,_,_ = workspace
    body = dict(name='开发服务',mode='host',scheme='http',port=3000,path='/ui?q=1',group='开发')
    response = client.post('/api/applications',json=body)
    assert response.status_code == 200
    saved = response.json()
    assert client.get('/api/applications').json()['applications'] == [saved]
    updated = client.post('/api/applications/'+saved['id'],json={**body,'name':'新名称','revision':saved['revision']})
    assert updated.status_code == 200
    assert client.post('/api/applications/'+saved['id'],json={**body,'revision':saved['revision']}).status_code == 409
    assert client.post('/api/applications/'+saved['id']+'/remove',json={'revision':saved['revision']}).status_code == 409
    assert client.post('/api/applications/'+saved['id']+'/remove',json={'revision':updated.json()['revision']}).status_code == 200
    assert client.get('/api/applications').json()['applications'] == []
    client.post('/api/logout',json={})
    assert client.get('/api/applications').status_code == 401
    assert client.post('/api/applications',json=body).status_code == 401
    assert client.get('/api/local-services').status_code == 401


@pytest.mark.parametrize('data',[
    dict(mode='host',port=0),dict(mode='host',port=65536),dict(mode='host',port=3000,path='//other.test'),
    dict(mode='host',port=3000,path='/\\other.test'),dict(mode='host',port=3000,path='/\n'),
    dict(mode='custom',url='javascript:alert(1)'),dict(mode='custom',url='file:///etc/passwd'),
    dict(mode='custom',url='http://localhost:99999'),dict(mode='custom',url='https://'),dict(mode='unknown'),
])
def test_application_invalid_addresses(data):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):applications.values(applications.Application(name='test',**data))


def test_custom_address_and_name_order(workspace):
    client,_,_ = workspace
    for name,url in [('zeta','https://example.org/path?q=1#section'),('Alpha','http://[::1]:3000/')]:
        assert client.post('/api/applications',json=dict(name=name,mode='custom',url=url)).status_code == 200
    assert [row['name'] for row in client.get('/api/applications').json()['applications']] == ['Alpha','zeta']


def test_saved_service_tunnel_is_authenticated_and_carries_raw_http(workspace,monkeypatch):
    import socketserver
    import threading
    from starlette.websockets import WebSocketDisconnect
    from app import main, modules
    client,_,_ = workspace
    monkeypatch.setattr(modules,'enabled',lambda key:True)
    payload=b'x'*70000
    class Service(socketserver.BaseRequestHandler):
        def handle(self):
            request=self.request.recv(65536)
            assert b'GET / HTTP/1.1' in request
            self.request.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 70000\r\n\r\n'+payload)
    with socketserver.TCPServer(('127.0.0.1',0),Service) as server:
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        saved=client.post('/api/applications',json=dict(name='本机服务',port=server.server_address[1])).json()
        path=f'ws://127.0.0.1:{main.PORT}/api/applications/'+saved['id']+'/tunnel'
        origin=f'http://127.0.0.1:{main.PORT}'
        try:
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(path,headers={'Origin':'http://evil.test'}):pass
            with client.websocket_connect(path,headers={'Origin':origin}) as ws:
                ws.send_bytes(b'GET / HTTP/1.1\r\nHost: app.localhost\r\n\r\n')
                received=b''
                while not received.endswith(payload):received+=ws.receive_bytes()
                assert received.endswith(payload)
            client.post('/api/logout',json={})
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(path,headers={'Origin':origin}):pass
        finally:
            server.shutdown();thread.join()
