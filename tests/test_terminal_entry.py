import sys,secrets,time,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import pytest
from fastapi.testclient import TestClient
from app import main,passwords,terminal_entry as entry
from app.zellij_sessions import host_sessions
REAL_DATA=main.DATA
BASE=f'http://127.0.0.1:{main.PORT}'

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    passwords.save('temporary-workflow-test-password',initial=True)
    c=TestClient(main.app,base_url=BASE,headers={'X-ORH-Request':'1','Origin':BASE})
    main.attempts.clear()
    assert c.post('/api/login',json={'password':'temporary-workflow-test-password'}).status_code==200
    yield c


def test_entry_reuses_without_shell_or_confirmation(monkeypatch):
    monkeypatch.setattr(entry,'host_sessions',lambda:[dict(name='existing',status='running')])
    monkeypatch.setattr(entry,'ensure_web',lambda:None)
    monkeypatch.setattr(main,'cli',lambda *args:pytest.fail('Existing session must not be recreated'))
    monkeypatch.setattr(main,'audit',lambda *a:None)
    assert entry.prepare('existing')=={'url':'/terminal/existing','state':'reused','session':'existing'}


def test_restore_never_force_runs_archived_commands(monkeypatch):
    rows=[dict(name='saved',status='exited')];commands=[]
    monkeypatch.setattr(entry,'host_sessions',lambda:rows)
    monkeypatch.setattr(entry,'ensure_web',lambda:None)
    monkeypatch.setattr(main,'audit',lambda *a:None)
    def create(args,timeout):
        commands.append(args);rows[0]['status']='running';return ''
    monkeypatch.setattr(main,'cli',create)
    assert entry.prepare('saved')['state']=='restored'
    assert len(commands)==1 and '--create-background' in commands[0]
    assert not any('force-run' in arg for arg in commands[0])


def test_launcher_permissions_and_validation(client,monkeypatch):
    monkeypatch.setattr(entry,'prepare',lambda name:{'url':'/terminal/'+name,'state':'reused'})
    assert client.get('/terminal/open/test').status_code==200
    assert client.post('/api/zellij/test/enter',json={}).status_code==200
    assert client.post('/api/zellij/test/enter',json={},headers={'Origin':'https://evil.test'}).status_code==403
    client.post('/api/logout',json={})
    assert client.post('/api/zellij/test/enter',json={}).status_code==401
    assert client.get('/terminal/open/--help').status_code==400


@pytest.mark.live
def test_real_create_reuse_restore_with_one_entry(client):
    name='orh-flow-'+secrets.token_hex(3)
    def row():return next((r for r in host_sessions() if r['name']==name),None)
    def stop_own():
        main.command(['zellij','--session',name,'action','save-session'],3)
        main.command(['zellij','kill-session',name],3)
        for n in range(25):
            if not row() or row()['status']!='running':return
            if n==8:main.command(['zellij','kill-session',name],3)
            time.sleep(.1)
        raise AssertionError('Own test session did not exit')
    try:
        response=client.post('/api/zellij/'+name+'/enter',json={})
        assert response.status_code==200,response.text
        assert response.json()['state']=='created'
        original=row()['pid']
        response=client.post('/api/zellij/'+name+'/enter',json={})
        assert response.json()['state']=='reused' and row()['pid']==original
        stop_own()
        assert row()['status']=='exited'
        response=client.post('/api/zellij/'+name+'/enter',json={})
        assert response.status_code==200,response.text
        assert response.json()['state']=='restored'
        assert row()['status']=='running' and row()['pid']!=original
    finally:
        if row() and row()['status']=='running':stop_own()
        if row():main.zellij_action(name,main.Action(action='delete',confirm=name))


def test_task_plain_command_parses_without_shell(client):
    r=client.post('/api/tasks',json={'name':'quoted arguments','command':'python3 -c "print(123)"','cwd':str(main.ROOT)})
    assert r.status_code==200,r.text
    task=next(t for t in client.get('/api/tasks').json() if t['id']==r.json()['id'])
    assert task['argv']==['python3','-c','print(123)']
    for command in ['echo one && echo two','echo "unfinished','']:
        assert client.post('/api/tasks',json={'name':'invalid','command':command,'cwd':str(main.ROOT)}).status_code==400


def test_two_browsers_do_not_create_duplicate_session(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    rows=[];creates=[]
    monkeypatch.setattr(entry,'host_sessions',lambda:list(rows))
    monkeypatch.setattr(entry,'ensure_web',lambda:None)
    monkeypatch.setattr(main,'audit',lambda *a:None)
    def create(args,timeout):
        time.sleep(.05);creates.append(args);rows.append(dict(name='parallel',status='running'));return ''
    monkeypatch.setattr(main,'cli',create)
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(entry.prepare,['parallel','parallel']))
    assert len(creates)==1
    assert {r['state'] for r in results}=={'created','reused'}
