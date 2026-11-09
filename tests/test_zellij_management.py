import sys,secrets,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import pytest
from fastapi.testclient import TestClient
from app import main,passwords
from app.zellij_sessions import host_sessions

@pytest.fixture
def c(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    passwords.save('local-hierarchy-test-password',initial=True)
    main.attempts.clear()
    client=TestClient(main.app,base_url=f'http://127.0.0.1:{main.PORT}',headers={'X-ORH-Request':'1'})
    assert client.post('/api/login',json={'password':'local-hierarchy-test-password'}).status_code==200
    return client


def test_ai_routes_and_special_session_rules_removed(c,monkeypatch):
    assert c.get('/api/agent').status_code==404
    assert c.get('/api/ai/threads').status_code==404
    from app import terminal_entry as entry
    monkeypatch.setattr(entry,'host_sessions',lambda:[dict(name='codex-agent',status='running')])
    monkeypatch.setattr(entry,'ensure_web',lambda:None)
    monkeypatch.setattr(main,'audit',lambda *a:None)
    monkeypatch.setattr(main,'cli',lambda *a:pytest.fail('Ordinary session entry must not launch Codex'))
    assert entry.prepare('codex-agent')['state']=='reused'


def test_unknown_delete_is_idempotent(c):
    r=c.post('/api/zellij/orh-nonexistent/delete',json={})
    assert r.status_code==404
    r=c.post('/api/zellij/orh-nonexistent',json={'action':'delete','confirm':'orh-nonexistent'})
    assert r.status_code==200 and r.json()['already_deleted']
    assert c.post('/api/zellij/orh-nonexistent',json={'action':'delete'}).status_code==400



def test_console_has_no_tab_or_pane_endpoints(c):
    for path in ['/structure','/panes','/output']:
        assert c.get('/api/zellij/ordinary'+path).status_code==404
    for path in ['/tabs','/tabs/0','/panes/terminal_0']:
        assert c.post('/api/zellij/ordinary'+path,json={'action':'close','confirm':'ordinary'}).status_code==404


def test_native_gateway_does_not_send_unsupported_heartbeat(monkeypatch):
    from app import native_terminal as native
    captured={}
    monkeypatch.setattr(native.websockets,'connect',lambda *a,**kw:captured.update(kw))
    native.native_connection('ws://127.0.0.1:8082/ws/terminal/test','private')
    assert captured['ping_interval'] is None
    assert captured['close_timeout']==2


@pytest.mark.live
def test_real_session_lifecycle_only(c):
    name='orh-session-'+secrets.token_hex(3)
    baseline={s['name'] for s in host_sessions()}
    path='/api/zellij/'+name
    def change(action):
        r=c.post(path,json={'action':action,'confirm':name})
        assert r.status_code==200,r.text
        return r.json()
    try:
        assert c.post(path+'/enter',json={}).status_code==200
        r=c.post(path,json={'action':'delete','confirm':name})
        assert r.status_code==409
        change('kill')
        assert next(s for s in host_sessions() if s['name']==name)['status']=='exited'
        result=change('delete')
        assert result.get('backup')
        assert change('delete')['already_deleted']
        assert c.post(path+'/enter',json={}).status_code==200
        change('purge')
    finally:
        if any(s['name']==name for s in host_sessions()):change('purge')
    assert {s['name'] for s in host_sessions()}==baseline
