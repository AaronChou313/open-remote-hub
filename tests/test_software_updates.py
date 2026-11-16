import time
from pathlib import Path
from test_files import workspace
from app import software_updates as updates, launcher


def test_release_check_and_download_use_the_existing_launcher(workspace,monkeypatch,tmp_path):
    client,_,_=workspace
    payload=tmp_path/'installer.exe';payload.write_bytes(b'fixture installer')
    release=dict(version='99.0.0',name='ORH-Setup-99.0.0.exe',url=payload.as_uri(),size=payload.stat().st_size,notes='Fixture release')
    monkeypatch.setattr(launcher,'release_info',lambda:release)
    monkeypatch.setattr(updates.tempfile,'gettempdir',lambda:str(tmp_path))
    monkeypatch.setattr(updates,'state',dict(phase='idle',progress=0,error='',release=None))
    assert client.get('/api/client/software').status_code==200
    assert client.post('/api/client/software/check',json={}).status_code==200
    for _ in range(100):
        result=client.get('/api/client/software').json()
        if result['phase']!='checking':break
        time.sleep(.01)
    assert result['phase']=='available'
    assert result['release']['version']=='99.0.0'
    client.post('/api/client/software/download',json={})
    for _ in range(100):
        result=client.get('/api/client/software').json()
        if result['phase']!='downloading':break
        time.sleep(.01)
    assert result['phase']=='ready'
    assert result['progress']==100
    assert Path(result['path']).read_bytes()==payload.read_bytes()
    monkeypatch.setattr(updates.sys,'frozen',True,raising=False)
    launched=[];monkeypatch.setattr(updates,'launch_installer',lambda path:launched.append(path))
    assert client.post('/api/client/software/install',json={}).status_code==200
    assert launched==[result['path']]
    client.post('/api/logout',json={})
    assert client.post('/api/client/software/install',json={}).status_code==401


def test_release_error_is_visible(workspace,monkeypatch):
    client,_,_=workspace
    monkeypatch.setattr(updates,'state',dict(phase='idle',progress=0,error='',release=None))
    def unavailable():raise OSError('offline')
    monkeypatch.setattr(launcher,'release_info',unavailable)
    updates.check_release()
    result=client.get('/api/client/software').json()
    assert result['phase']=='error' and 'offline' in result['error']
