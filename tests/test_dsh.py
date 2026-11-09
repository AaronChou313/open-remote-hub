import asyncio
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from app import main,passwords,access,dsh,dsh_gateway as gateway
from app.network import Network


@pytest.fixture
def dsh_client(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    monkeypatch.setattr(main,'NETWORK',Network('0.0.0.0',frozenset({'127.0.0.1','localhost','192.168.31.160','100.66.1.4'})))
    monkeypatch.setenv('ORH_DSH_ENABLED','1');monkeypatch.setenv('ORH_DSH_GATEWAY_PORT','8767');monkeypatch.setenv('ORH_DSH_PORT','9741')
    main.attempts.clear();passwords.save('dsh-isolated-test-password',initial=True)
    c=TestClient(main.app,base_url=f'http://127.0.0.1:{main.PORT}',headers={'X-ORH-Request':'1'})
    assert c.post('/api/login',json={'password':'dsh-isolated-test-password'}).status_code==200
    token=c.cookies.get('orh')
    target=TestClient(gateway.app,base_url='http://127.0.0.1:8767',headers={'Cookie':'orh='+token})
    monkeypatch.setattr(gateway,'connections',{})
    monkeypatch.setattr(dsh,'native_cookie',lambda:'native-cookie=unit-test-only')
    return c,target,token


class Bytes(httpx.AsyncByteStream):
    async def __aiter__(self):yield b'official-ui-bytes'


def test_http_auth_origin_and_credential_isolation(dsh_client,monkeypatch):
    c,target,token=dsh_client;observed=[]
    async def request(req):
        observed.append(req)
        return httpx.Response(200,headers={'Content-Type':'text/html','Set-Cookie':'native-secret=never-forward'},stream=Bytes())
    monkeypatch.setattr(gateway,'client',httpx.AsyncClient(transport=httpx.MockTransport(request)))
    r=target.get('/');assert r.status_code==200 and r.content==b'official-ui-bytes'
    assert 'set-cookie' not in r.headers
    assert 'frame-ancestors' in r.headers['content-security-policy']
    assert observed[0].url.host=='127.0.0.1' and observed[0].url.port==9741
    assert observed[0].headers['cookie']=='native-cookie=unit-test-only' and token not in observed[0].headers['cookie']
    assert 'authorization' not in observed[0].headers
    assert target.post('/api/settings.update').status_code==403
    assert target.post('/api/settings.update',headers={'Origin':'http://evil.test'}).status_code==403
    assert target.post('/api/session.list',headers={'Origin':'http://127.0.0.1:8767'}).status_code==200
    assert observed[-1].headers['origin']=='http://127.0.0.1:9741'
    assert target.get('/',headers={'Host':'evil.test:8767'}).status_code==400
    assert target.get('/',headers={'Origin':'http://localhost:8767'}).status_code==403
    c.post('/api/logout',json={})
    assert target.get('/').status_code==401
    assert target.post('/api/session.list',headers={'Origin':'http://127.0.0.1:8767'}).status_code==401


@pytest.mark.parametrize('channel',['remote.mux'])
def test_socket_auth_origin_and_revocation(dsh_client,monkeypatch,channel):
    c,target,token=dsh_client;captured={}
    class Backend:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def send(self,data):pytest.fail('Revoked client data reached the native service')
        async def messages(self):
            yield 'native-event'
            await asyncio.Event().wait()
        def __aiter__(self):return self.messages()
    def connect(url,**kw):captured.update(url=url,**kw);return Backend()
    monkeypatch.setattr(gateway.websockets,'connect',connect)
    url='ws://127.0.0.1:8767/api/'+channel
    for origin in ('http://evil.test','http://localhost:8767',''):
        with pytest.raises(WebSocketDisconnect):
            with target.websocket_connect(url,headers={'Origin':origin}):pass
    with target.websocket_connect(url,headers={'Origin':'http://127.0.0.1:8767'}) as ws:
        assert ws.receive_text()=='native-event'
        assert captured['url']=='ws://127.0.0.1:9741/api/'+channel
        assert captured['additional_headers']=={'Cookie':'native-cookie=unit-test-only'}
        access.revoke(token)
        ws.send_text('must-not-forward-after-revocation')
        with pytest.raises(WebSocketDisconnect):ws.receive_text()
    assert not gateway.connections


def test_dsh_controls_reuse_and_no_accidental_start(dsh_client,monkeypatch):
    c,target,token=dsh_client
    monkeypatch.setattr(dsh,'installation',lambda:{'argv':['node','/trusted/dsh.js'],'version':'0.2.2-rc.1'})
    class Process:pid=1234
    monkeypatch.setattr(dsh,'managed',lambda:Process())
    monkeypatch.setattr(dsh,'healthy',lambda:True)
    monkeypatch.setattr(dsh.subprocess,'Popen',lambda *a,**kw:pytest.fail('Existing native host must not restart'))
    assert c.post('/api/dsh/start',json={}).json()['pid']==1234
    assert c.get('/api/dsh/status').json()['running']
    access.revoke(token)
    assert c.post('/api/dsh/start',json={}).status_code==401


def test_dispatch_uses_socket_port_not_host_header(dsh_client,monkeypatch):
    c,target,token=dsh_client
    async def request(req):return httpx.Response(200,headers={'content-type':'text/html'},stream=Bytes())
    monkeypatch.setattr(gateway,'client',httpx.AsyncClient(transport=httpx.MockTransport(request)))
    dispatch=gateway.Dispatch(main.app,8767)
    with TestClient(dispatch,base_url=f'http://127.0.0.1:{main.PORT}',headers={'Cookie':'orh='+token}) as client:
        assert 'OpenRemoteHub' in client.get('/').text
        assert client.get('/',headers={'Host':'127.0.0.1:8767'}).status_code==400
    monkeypatch.setattr(gateway,'client',httpx.AsyncClient(transport=httpx.MockTransport(request)))
    with TestClient(dispatch,base_url='http://127.0.0.1:8767',headers={'Cookie':'orh='+token}) as client:
        assert client.get('/').content==b'official-ui-bytes'


def test_dsh_files_are_protected():
    from app.file_access import parts
    from fastapi import HTTPException
    for path in ('.dsh/.credentials.yaml','somewhere/.credentials.yaml'):
        with pytest.raises(HTTPException):parts(path)


def test_explicit_old_cli_is_not_silently_used(tmp_path,monkeypatch):
    root=tmp_path/'old';(root/'lib').mkdir(parents=True)
    (root/'package.json').write_text('{"name":"@deepseek-ai/dsh","version":"0.1.0-rc.6"}')
    script=root/'lib/bin.js';script.write_text('// fixture only')
    monkeypatch.setenv('ORH_DSH_BIN',str(script))
    assert dsh.installation() is None
    (root/'package.json').write_text('{"name":"@deepseek-ai/dsh","version":"0.2.2-rc.1"}')
    # A JS entry needs Node; use a known synthetic executable, never launch it.
    monkeypatch.setattr(dsh.shutil,'which',lambda name:'/trusted/node')
    assert dsh.installation()['version']=='0.2.2-rc.1'


def test_unknown_socket_route_is_never_proxied(dsh_client,monkeypatch):
    c,target,token=dsh_client
    monkeypatch.setattr(gateway.websockets,'connect',lambda *a,**kw:pytest.fail('Unsupported socket must not reach native host'))
    with pytest.raises(WebSocketDisconnect):
        with target.websocket_connect('ws://127.0.0.1:8767/http://evil.test',headers={'Origin':'http://127.0.0.1:8767'}):pass


def test_native_auth_logs_redact_launch_token(tmp_path):
    from app.dsh_auth import redact,save
    token='synthetic-launch-secret-for-unit-test'
    assert token not in redact('dsh web: http://127.0.0.1:9741/?token='+token+'\n')
    save(tmp_path,dict(port=9741,cookie='unit-cookie',launch_token=token,renew_after=123))
    assert (tmp_path/'dsh-auth.json').stat().st_mode&0o777==0o600
    assert not list(tmp_path.glob('.dsh-auth-*'))


def test_managed_pid_tolerates_clock_rounding(dsh_client,monkeypatch):
    import json
    from app.dsh import state_path
    state_path().write_text(json.dumps({'pid':123,'created':1000.001,'argv':['python','/owned/dsh_host.py','/owned/plan.json']}))
    class Process:
        def create_time(self):return 1000.001001
        def status(self):return 'running'
        def cmdline(self):return ['Python','/owned/dsh_host.py','/owned/plan.json']
    monkeypatch.setattr(dsh.psutil,'Process',lambda pid:Process())
    assert dsh.managed()
    monkeypatch.setattr(Process,'create_time',lambda self:1001)
    assert not dsh.managed()
