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


@pytest.mark.live
def test_real_session_tab_pane_lifecycle(c):
    name='orh-tree-'+secrets.token_hex(3)
    baseline={s['name'] for s in host_sessions()}
    assert c.post('/api/zellij/'+name+'/enter',json={}).status_code==200
    path='/api/zellij/'+name
    def change(url,action,**kw):
        r=c.post(url,json={'action':action,'confirm':name,**kw})
        assert r.status_code==200,r.text
        return r.json()
    def structure():
        r=c.get(path+'/structure');assert r.status_code==200,r.text;return r.json()
    try:
        first=structure()['tabs'][0]
        assert first['panes'] and first['plugins']
        change(path+'/tabs','create',name='work')
        tab=next(t for t in structure()['tabs'] if t['name']=='work')
        change(path+'/tabs/'+str(tab['id']),'rename',name='renamed')
        assert next(t for t in structure()['tabs'] if t['id']==tab['id'])['name']=='renamed'
        original={p['id'] for p in first['panes']}
        change(path+'/tabs/'+str(first['id']),'pane')
        for _ in range(15):
            now=next(t for t in structure()['tabs'] if t['id']==first['id'])
            added=[p for p in now['panes'] if p['id'] not in original]
            if added:break
            time.sleep(.1)
        assert added
        change(path+'/panes/'+added[0]['id'],'close')
        assert c.post(path+'/panes/plugin_1',json={'action':'close','confirm':name}).status_code==400
        change(path+'/tabs/'+str(tab['id']),'close')
        assert len(structure()['tabs'])==1
        # Active deletion requires explicit end-and-delete, not an ambiguous history delete.
        assert c.post(path,json={'action':'delete','confirm':name}).status_code==409
        result=change(path,'purge')
        assert result.get('backup')
        assert not any(s['name']==name for s in host_sessions())
        assert change(path,'delete')['already_deleted']
    finally:
        if any(s['name']==name for s in host_sessions()):change(path,'purge')
    assert {s['name'] for s in host_sessions()}==baseline
