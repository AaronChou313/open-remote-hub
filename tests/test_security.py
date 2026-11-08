import secrets
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient
import app.main as main
from app import passwords,access
import pytest


TEST_PASSWORD='isolated-test-password-中文'

@pytest.fixture(autouse=True)
def password_store(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    main.attempts.clear()

def login(c):
    if not passwords.record():passwords.save(TEST_PASSWORD,initial=True)
    return c.post('/api/login',json={'password':TEST_PASSWORD})

def viewer(c):
    if not passwords.record():passwords.save(TEST_PASSWORD,initial=True)
    import time
    token=secrets.token_urlsafe(32);access.create(token,'viewer',time.time()+300)
    c.cookies.set('orh',token)

def client():return TestClient(main.app,base_url='http://127.0.0.1:'+str(main.PORT),headers={'X-ORH-Request':'1'})


def test_viewer_cannot_execute_or_create_terminal_token():
    c=client()
    viewer(c)
    assert c.get('/api/me').json()['role']=='viewer'
    for path,body in [('/api/tasks',{}),('/api/zellij-web',{'action':'token','confirm':'zellij-web'}),('/api/docker/'+'a'*12,{'action':'start','confirm':'a'*12}),('/api/zellij/test',{'action':'create','confirm':'test'})]:
        assert c.post(path,json=body).status_code==403
    assert c.post('/api/logout',json={}).status_code==200
    assert c.get('/api/me').status_code==401


def test_auth_origin_and_confirmation_guards():
    c=client()
    assert c.get('/api/system').status_code==401
    assert c.post('/api/login',json={'password':'wrong'}).status_code==401
    assert login(c).status_code==200
    assert c.get('/api/system',headers={'host':'evil.test'}).status_code==400
    assert c.post('/api/logout',json={},headers={'origin':'https://evil.test'}).status_code==403
    assert c.post('/api/docker/'+'a'*12,json={'action':'stop'}).status_code==400
    assert c.post('/api/docker/--help',json={'action':'start','confirm':'--help'}).status_code==400
    assert c.post('/api/zellij/--help',json={'action':'create','confirm':'--help'}).status_code==400
    assert c.post('/api/tasks/not-managed',json={'action':'stop','confirm':'not-managed'}).status_code==404


def test_recycled_or_foreign_pid_is_never_owned():
    import os
    assert main.task_process({'pid':os.getpid(),'created':0}) is None


def test_login_rate_limit():
    c=client();main.attempts.clear()
    for _ in range(8):assert c.post('/api/login',json={'password':'wrong'}).status_code==401
    assert c.post('/api/login',json={'password':'wrong'}).status_code==429
    main.attempts.clear()


def test_stopped_service_does_not_resolve_current_process():
    from app.platforms import process_detail
    assert process_detail(None) is None
    assert process_detail(0) is None


def test_unicode_invalid_token_is_rejected_not_server_error():
    c=client()
    assert c.post('/api/login',json={'password':'错误密码'}).status_code==401


def test_restart_refuses_surviving_child(tmp_path,monkeypatch):
    import os,time,json,psutil
    monkeypatch.setattr(main,'DATA',tmp_path)
    c=client();assert login(c).status_code==200
    child_code='import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print("CHILD_READY",flush=True); time.sleep(30)'
    parent_code='import subprocess,sys,time; subprocess.Popen([sys.executable,"-u","-c",'+repr(child_code)+']); time.sleep(30)'
    r=c.post('/api/tasks',json={'name':'orh-child-guard','argv':[sys.executable,'-u','-c',parent_code],'cwd':str(tmp_path)})
    assert r.status_code==200
    key=r.json()['id'];child=None
    payload=lambda a:{'action':a,'confirm':key}
    try:
        assert c.post('/api/tasks/'+key,json=payload('start')).status_code==200
        for _ in range(40):
            if 'CHILD_READY' in c.get('/api/tasks/'+key+'/logs').json()['output']:break
            time.sleep(.05)
        else:raise AssertionError('child did not initialize')
        task=next(t for t in c.get('/api/tasks').json() if t['id']==key)
        child=psutil.Process(task['pid']).children()[0];identity=child.create_time()
        assert c.post('/api/tasks/'+key,json=payload('restart')).status_code==409
        assert c.post('/api/tasks/'+key,json=payload('start')).status_code==409
        assert child.is_running() and child.create_time()==identity
    finally:
        if child and child.is_running() and child.create_time()==identity:
            child.kill();child.wait(5)
        c.post('/api/tasks/'+key,json=payload('stop'))
        c.post('/api/tasks/'+key,json=payload('delete'))
