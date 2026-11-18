import sys,secrets,time,subprocess,socket,tempfile,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import pytest
import psutil
from fastapi import HTTPException
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


def test_delete_saved_session_does_not_query_stalled_peers(c,tmp_path,monkeypatch):
    from app import zellij_manage as manage,zellij_sessions as sessions
    root=tmp_path/'cache'
    folder=root/'contract_version_1/session_info/saved'
    folder.mkdir(parents=True);(folder/'session-layout.kdl').write_text('layout {}')
    monkeypatch.setattr(sessions,'cache_roots',lambda:[root])
    monkeypatch.setattr(manage,'host_sessions',lambda:[dict(name='saved',status='exited')] if folder.exists() else [])
    monkeypatch.setattr(main,'cli',lambda *a,**kw:pytest.fail('Deleting saved files must not scan other session sockets'))
    response=c.post('/api/zellij/saved',json={'action':'delete','confirm':'saved'})
    assert response.status_code==200,response.text
    assert not folder.exists()
    assert (main.DATA/response.json()['backup']/'contract_version_1/saved/session-layout.kdl').exists()
    assert c.post('/api/zellij/saved',json={'action':'delete','confirm':'saved'}).json()['already_deleted']


@pytest.mark.parametrize('action',['kill','purge'])
def test_unresponsive_session_ends_its_process_tree(c,tmp_path,monkeypatch,action):
    from app import zellij_manage as manage,zellij_sessions as sessions
    root=tmp_path/'cache'
    folder=root/'contract_version_1/session_info/owned'
    folder.mkdir(parents=True);(folder/'session-layout.kdl').write_text('layout {}')
    code="import subprocess,sys,time; child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']); print(child.pid,flush=True); time.sleep(120)"
    process=subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.PIPE,text=True)
    unrelated=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'])
    child=psutil.Process(int(process.stdout.readline()))
    row=dict(name='owned',status='running',pid=process.pid,created=psutil.Process(process.pid).create_time())
    def rows():
        if process.poll() is None:return [row]
        return [dict(name='owned',status='exited')] if folder.exists() else []
    commands=[]
    def unavailable(args,*a,**kw):
        commands.append(args)
        raise HTTPException(503,'Zellij IPC timed out')
    monkeypatch.setattr(sessions,'cache_roots',lambda:[root])
    monkeypatch.setattr(manage,'host_sessions',rows)
    monkeypatch.setattr(main,'cli',unavailable)
    try:
        response=c.post('/api/zellij/owned',json={'action':action,'confirm':'owned'})
        assert response.status_code==200,response.text
        assert process.poll() is not None
        assert not child.is_running() or child.status()==psutil.STATUS_ZOMBIE
        assert unrelated.poll() is None
        assert folder.exists()==(action=='kill')
        assert not any('delete-session' in args for args in commands)
        assert any('save-session' in args for args in commands)==(action=='kill')
    finally:
        for member in [child,psutil.Process(unrelated.pid)]:
            if member.is_running():member.kill()
        if process.poll() is None:process.kill()
        process.wait();unrelated.wait();process.stdout.close()


def test_reused_session_pid_is_not_terminated(c,monkeypatch):
    from app import zellij_manage as manage
    process=psutil.Process()
    monkeypatch.setattr(manage,'host_sessions',lambda:[dict(name='reused',status='running',pid=process.pid,created=process.create_time()-1)])
    monkeypatch.setattr(manage,'backup',lambda name:None)
    response=c.post('/api/zellij/reused',json={'action':'purge','confirm':'reused'})
    assert response.status_code==409
    assert '进程已变化' in response.json()['detail']


@pytest.mark.live
def test_real_session_lifecycle_only(c):
    name='orh-session-'+secrets.token_hex(3)
    original=name
    baseline={s['name'] for s in host_sessions()}
    path='/api/zellij/'+name
    def change(action):
        r=c.post(path,json={'action':action,'confirm':name})
        assert r.status_code==200,r.text
        return r.json()
    try:
        assert c.post(path+'/enter',json={}).status_code==200
        renamed=name+'r'
        response=c.post(path,json={'action':'rename','name':renamed,'confirm':name})
        assert response.status_code==200,response.text
        name=renamed;path='/api/zellij/'+name
        assert next(s for s in host_sessions() if s['name']==name)['status']=='running'
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
        from app.zellij_manage import delete_history
        delete_history(original)
    assert {s['name'] for s in host_sessions()}==baseline


@pytest.mark.live
def test_real_session_delete_with_stalled_peer(c,monkeypatch):
    name='orh-stall-'+secrets.token_hex(3)
    path='/api/zellij/'+name
    baseline={s['name'] for s in host_sessions()}
    with tempfile.TemporaryDirectory(prefix='orh-z-',dir='/tmp') as value:
        monkeypatch.setenv('ZELLIJ_SOCKET_DIR',value)
        response=c.post(path+'/enter',json={})
        assert response.status_code==200,response.text
        peer=Path(value)/'contract_version_1/blocked'
        listener=socket.socket(socket.AF_UNIX)
        listener.bind(str(peer));listener.listen(32);listener.settimeout(.1)
        clients=[];done=threading.Event()
        def accept():
            while not done.is_set():
                try:clients.append(listener.accept()[0])
                except socket.timeout:continue
        thread=threading.Thread(target=accept);thread.start()
        try:
            started=time.monotonic()
            response=c.post(path,json={'action':'purge','confirm':name})
            assert response.status_code==200,response.text
            assert time.monotonic()-started<10
            assert not any(s['name']==name for s in host_sessions())
            assert response.json()['backup']
            response=c.post(path,json={'action':'delete','confirm':name})
            assert response.status_code==200 and response.json()['already_deleted']
        finally:
            done.set();thread.join(2)
            for client in clients:client.close()
            listener.close();peer.unlink(missing_ok=True)
            if any(s['name']==name for s in host_sessions()):
                response=c.post(path,json={'action':'purge','confirm':name})
                assert response.status_code==200,response.text
    assert {s['name'] for s in host_sessions()}==baseline
