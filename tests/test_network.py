"""Private-network destinations must not weaken Host, Origin or login guards."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from app import main,passwords,native_terminal
from app.network import Network


@pytest.fixture
def network(tmp_path,monkeypatch):
    monkeypatch.setenv('ORH_HOST','0.0.0.0')
    monkeypatch.setenv('ORH_ALLOWED_HOSTS','192.168.31.160,100.66.1.2,100.66.1.4,10.77.1.2,10.77.1.4,server.local')
    config=Network.load()
    monkeypatch.setattr(main,'NETWORK',config)
    monkeypatch.setattr(main,'DATA',tmp_path)
    main.attempts.clear()
    return config


def test_defaults_and_portability(monkeypatch):
    monkeypatch.delenv('ORH_HOST',raising=False)
    monkeypatch.delenv('ORH_ALLOWED_HOSTS',raising=False)
    n=Network.load()
    assert n.bind=='127.0.0.1'
    assert n.allows('127.0.0.1:8765',8765)
    assert not n.allows('192.168.31.160:8765',8765)
    monkeypatch.setenv('ORH_HOST','192.168.1.25')
    n=Network.load()
    assert n.allows('192.168.1.25:9000',9000)
    assert n.local_url(9000)=='http://192.168.1.25:9000'
    monkeypatch.setenv('ORH_HOST','::')
    assert Network.load().local_url(9000)=='http://[::1]:9000'


@pytest.mark.parametrize('bad',['*','http://server.local','server.local:8765','evil/path','0.0.0.0','::'])
def test_reject_ambiguous_or_wildcard_configuration(monkeypatch,bad):
    monkeypatch.setenv('ORH_ALLOWED_HOSTS',bad)
    with pytest.raises(ValueError):Network.load()


@pytest.mark.parametrize('address',['192.168.31.160','100.66.1.2','100.66.1.4','10.77.1.2','10.77.1.4','server.local'])
def test_private_network_login_and_terminal_guards(network,address,monkeypatch):
    origin=f'http://{address}:{main.PORT}'
    passwords.save('network-test-password',initial=True)
    with TestClient(main.app,base_url=origin,headers={'Origin':origin,'X-ORH-Request':'1'}) as c:
        assert c.get('/').status_code==200
        assert c.get('/api/me').status_code==401
        assert c.get('/terminal/dev-demo').status_code==403
        assert c.post('/api/login',json={'password':'network-test-password'}).status_code==200
        assert c.get('/api/me').status_code==200
        assert c.get('/terminal/open/dev-demo').status_code==200
        # Two trusted destination aliases still cannot make cross-origin requests.
        assert c.post('/api/logout',headers={'Origin':f'http://localhost:{main.PORT}'}).status_code==403
        assert c.get('/',headers={'Host':f'evil.test:{main.PORT}'}).status_code==400
        assert c.post('/api/logout',headers={'X-ORH-Request':''}).status_code==403
        assert c.get('/').headers['content-security-policy'].find("connect-src 'self'")>=0
        for headers in ({'Origin':'http://evil.test'},{'Origin':f'http://localhost:{main.PORT}'}):
            with pytest.raises(WebSocketDisconnect):
                with c.websocket_connect(origin.replace('http:','ws:')+'/terminal/ws/control?web_client_id=test',headers=headers):pass
        # A valid authenticated same-origin socket reaches the native adapter.
        reached=[]
        async def upstream():
            reached.append(True)
            raise RuntimeError('No native server needed for policy test')
        monkeypatch.setattr(native_terminal.upstream,'authenticate',upstream)
        with pytest.raises(WebSocketDisconnect) as e:
            with c.websocket_connect(origin.replace('http:','ws:')+'/terminal/ws/control?web_client_id=test'):pass
        assert e.value.code==1013 and reached
        c.post('/api/logout')
        reached.clear()
        with pytest.raises(WebSocketDisconnect) as e:
            with c.websocket_connect(origin.replace('http:','ws:')+'/terminal/ws/control?web_client_id=test'):pass
        assert e.value.code==1008 and not reached


def test_remote_or_mapped_peer_cannot_initialize_password(network):
    origin=f'http://100.66.1.2:{main.PORT}'
    with TestClient(main.app,base_url=origin,client=('127.0.0.1',50000),headers={'Origin':origin,'X-ORH-Request':'1'}) as c:
        assert c.post('/api/auth/setup',json={'password':'network-test-password'}).status_code==403
        assert not passwords.record()


def test_https_cookie_and_ipv6(network):
    assert network.allows('[::1]:8765',8765)
    assert network.allows('server.local',443,'https')
    for authority in ('evil.test:8765','100.66.1.2:9999','100.66.1.2:','100.66.1.2:8765@evil.test','100.66.1.2:8765/','100.66.1.2:8765\\evil'):
        assert not network.allows(authority,8765)
    origin=f'https://server.local:{main.PORT}'
    passwords.save('network-test-password',initial=True)
    with TestClient(main.app,base_url=origin,headers={'Origin':origin,'X-ORH-Request':'1'}) as c:
        r=c.post('/api/login',json={'password':'network-test-password'})
        assert r.status_code==200 and 'secure' in r.headers['set-cookie'].lower()
        assert c.get('/api/me').status_code==200
