"""Password migration and the real authenticated Zellij Web gateway."""
import asyncio
import json
import os
import secrets
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from app import main,passwords,access,native_terminal

ORIGIN=f'http://127.0.0.1:{main.PORT}'
PASSWORD='temporary-test-密码-'+secrets.token_hex(6)
REAL_DATA=main.DATA

@pytest.fixture
def c(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    main.attempts.clear()
    with TestClient(main.app,base_url=ORIGIN,headers={'X-ORH-Request':'1','Origin':ORIGIN}) as client:
        # TestClient default peer is not loopback; explicit synthetic peer for setup.
        yield client


def auth(c):
    passwords.save(PASSWORD,initial=True)
    assert c.post('/api/login',json={'password':PASSWORD}).status_code==200


def test_password_storage_and_token_retirement(c):
    assert c.get('/api/auth/status').json()=={'needs_setup':True}
    assert c.post('/api/login',json={'token':'retired-token'}).status_code==422
    assert c.post('/api/auth/setup',json={'password':PASSWORD}).status_code==403
    passwords.save(PASSWORD,initial=True)
    assert os.stat(passwords.path()).st_mode & 0o777 == 0o600
    assert PASSWORD not in passwords.path().read_text()
    assert c.post('/api/login',json={'password':'错误密码'}).status_code==401
    assert c.post('/api/login',json={'password':PASSWORD}).status_code==200
    assert c.cookies.get('orh')
    assert c.get('/api/me').status_code==200


def test_setup_origin_atomic_and_policy(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    main.attempts.clear()
    with TestClient(main.app,base_url=ORIGIN,client=('127.0.0.1',50001),headers={'X-ORH-Request':'1','Origin':ORIGIN}) as c:
        assert c.post('/api/auth/setup',json={'password':'short'}).status_code==400
        assert c.post('/api/auth/setup',json={'password':PASSWORD},headers={'Origin':'http://evil.test'}).status_code==403
        assert c.post('/api/auth/setup',json={'password':PASSWORD}).status_code==200
        assert c.post('/api/auth/setup',json={'password':PASSWORD}).status_code==409
        assert c.get('/api/me').status_code==200


def test_password_change_revokes_sessions(c):
    auth(c)
    old=c.cookies.get('orh')
    assert c.post('/api/auth/password',json={'current_password':PASSWORD,'password':PASSWORD+'-new'}).status_code==200
    assert access.get(old) is None
    assert c.get('/api/me').status_code==200
    assert c.post('/api/logout',json={}).status_code==200
    assert c.get('/api/me').status_code==401


def test_origin_host_and_legacy_ws_closed(c):
    auth(c)
    assert c.get('/api/me',headers={'Host':'evil.test'}).status_code==400
    assert c.post('/terminal/session?session=codex-agent',headers={'Origin':'http://evil.test'}).status_code==403
    # Missing Origin cannot use the native API POST exemption.
    h={'Cookie':'orh='+c.cookies.get('orh'),'Host':f'127.0.0.1:{main.PORT}'}
    with TestClient(main.app,base_url=ORIGIN) as other:
        assert other.post('/terminal/session?session=codex-agent',headers=h).status_code==403
    for path in ['/ws/terminal/codex-agent','/terminal/ws/terminal/codex-agent']:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect(path,headers={'Origin':'http://evil.test'}):pass
    assert c.post('/terminal/command/login',json={'auth_token':'arbitrary'}).status_code==404
    assert c.get('/terminal/assets/../../.env').status_code!=200


def test_rate_limit_and_confirmation(c):
    auth(c)
    assert c.post('/api/docker/'+'a'*12,json={'action':'stop'}).status_code==400
    assert c.post('/api/zellij/--help',json={'action':'create','confirm':'--help'}).status_code==400
    main.attempts.clear()
    for _ in range(8):assert c.post('/api/login',json={'password':'incorrect'}).status_code==401
    assert c.post('/api/login',json={'password':'incorrect'}).status_code==429


@pytest.mark.live
def test_live_official_client_and_ws(c,monkeypatch):
    auth(c)
    # Reuse the real private gateway token without copying it into test reports.
    if not (REAL_DATA/'zellij-gateway.json').exists():pytest.skip('Start the local console and native gateway before this live test')
    (main.DATA/'zellij-gateway.json').write_bytes((REAL_DATA/'zellij-gateway.json').read_bytes())
    assert c.get('/terminal/codex-agent').status_code==200
    asset=c.get('/terminal/assets/app.js')
    assert asset.status_code==200 and b'import.meta.url' in asset.content
    assert 'set-cookie' not in asset.headers
    bootstrap=c.post('/terminal/session?session=codex-agent')
    assert bootstrap.status_code==200,bootstrap.text
    boot=bootstrap.json()
    assert boot['session_name']=='codex-agent'
    with c.websocket_connect(ORIGIN.replace('http:','ws:')+'/terminal/ws/terminal/codex-agent?web_client_id='+boot['web_client_id']+'&rows=30&cols=102',headers={'Origin':ORIGIN,'Host':f'127.0.0.1:{main.PORT}'}) as term:
        with c.websocket_connect(ORIGIN.replace('http:','ws:')+'/terminal/ws/control?web_client_id='+boot['web_client_id'],headers={'Origin':ORIGIN,'Host':f'127.0.0.1:{main.PORT}'}) as control:
            data=term.receive()
            assert data['type']=='websocket.send'
            assert control is not None
    assert c.get('/api/zellij/codex-agent/panes').status_code==200
    c.post('/api/logout',json={})
    assert c.get('/terminal/codex-agent').status_code==403


@pytest.mark.live
def test_live_utf8_two_clients_and_reconnect(c):
    import contextlib,time,psutil
    auth(c)
    if not (REAL_DATA/'zellij-gateway.json').exists():pytest.skip('Start the local console and native gateway before this live test')
    (main.DATA/'zellij-gateway.json').write_bytes((REAL_DATA/'zellij-gateway.json').read_bytes())
    name='orh-native-'+secrets.token_hex(3)
    url=ORIGIN.replace('http:','ws:')+'/terminal/ws/'
    headers={'Origin':ORIGIN,'Host':f'127.0.0.1:{main.PORT}'}
    def attach(stack):
        r=c.post('/terminal/session?session='+name)
        assert r.status_code==200,r.text
        ident=r.json()['web_client_id']
        terminal=stack.enter_context(c.websocket_connect(url+'terminal/'+name+'?web_client_id='+ident+'&rows=24&cols=100',headers=headers))
        stack.enter_context(c.websocket_connect(url+'control?web_client_id='+ident,headers=headers))
        return terminal
    assert c.post('/api/zellij/'+name,json={'action':'create','confirm':name}).status_code==200
    try:
        time.sleep(.5)
        with contextlib.ExitStack() as stack:
            first=attach(stack);second=attach(stack)
            first.send_text("printf '中文验证通过\\n'; sleep 45")
            first.send_text('\r')
            for _ in range(40):
                panes=main.cli(['zellij','--session',name,'action','list-panes','--all','--json'])
                if 'sleep 45' in panes:break
                time.sleep(.1)
            else:raise AssertionError('Native terminal command did not execute')
            assert '中文验证通过' in main.cli(['zellij','--session',name,'action','dump-screen'])
            server=next(p for p in psutil.process_iter(['cmdline']) if any('/'+name==a[-len(name)-1:] for a in (p.info['cmdline'] or [])) and '--server' in p.info['cmdline'])
            sleeper=next(p for p in server.children(recursive=True) if p.name()=='sleep')
            pid=sleeper.pid;created=sleeper.create_time()
        assert psutil.Process(pid).create_time()==created
        with contextlib.ExitStack() as stack:
            attach(stack)
            assert psutil.Process(pid).create_time()==created
        assert psutil.Process(pid).create_time()==created
    finally:
        result=c.post('/api/zellij/'+name,json={'action':'kill','confirm':name})
        assert result.status_code==200,result.text
        for _ in range(10):
            time.sleep(.1)
            result=c.post('/api/zellij/'+name,json={'action':'delete','confirm':name})
            if result.status_code==200:break
        assert result.status_code==200,result.text
