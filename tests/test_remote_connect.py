from pathlib import Path
import json
import socket
import sys
import threading
import tempfile

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.remote_connect.rustdesk import client, ipc
from app.remote_connect import api as web, tailscale
from app import main, access
from test_files import workspace
import time


class FakeNative:
    def __init__(self):
        self.values = {'direct-server':'Y', 'native-private-token':'fixture-only-secret', 'unrelated-option':'preserve'}
        self.password = None
        self.fail = False
    def options(self):return dict(self.values)
    def set_options(self, values):self.values = dict(values)
    def config(self, name):return {'id':'123456789','permanent-password-set':'Y','temporary-password':'fixture-secret'}[name]
    def request(self, kind):return {'OnlineStatus':[20,True],'VideoConnCount':1}[kind]
    def set_password(self, password):self.password = password


@pytest.fixture
def management(monkeypatch,tmp_path,workspace):
    native = FakeNative()
    monkeypatch.setattr(client,'native',native)
    monkeypatch.setattr(web,'native',native)
    monkeypatch.setattr(client,'processes',lambda:[])
    data = tmp_path/'native';data.mkdir()
    monkeypatch.setattr(client,'data_dir',lambda:data)
    monkeypatch.setattr(client,'autostart_path',lambda:data/'autostart.json')
    monkeypatch.setattr(tailscale,'status',lambda:dict(available=True,state='Running',peers=[]))
    monkeypatch.setattr(web.nodebaby,'status',lambda:dict(available=False,mappings=[],addresses=[]))
    audit=[]
    monkeypatch.setattr(web,'audit',lambda *args:audit.append(args))
    http=workspace[0]
    return http,native,audit


def test_status_settings_and_preserved_native_options(management):
    http,native,_ = management
    response = http.get('/api/remote-connect')
    assert response.status_code == 200
    assert response.json()['rustdesk']['device_id'] == '123456789'
    assert response.json()['rustdesk']['connections'] == 1
    options = http.get('/api/remote-connect/rustdesk/settings').json()['options']
    assert 'native-private-token' not in options
    response = http.post('/api/remote-connect/rustdesk/settings',json={'changes':{'enable-keyboard':'N'},'before':options})
    assert response.status_code == 200
    assert native.values['enable-keyboard'] == 'N'
    assert native.values['native-private-token'] == 'fixture-only-secret'
    assert native.values['unrelated-option'] == 'preserve'
    assert 'fixture-only-secret' not in response.text
    assert http.post('/api/remote-connect/rustdesk/settings',json={'changes':{'enable-keyboard':'Y'},'before':options}).status_code == 409


def test_authorization_hosts_csrf(management):
    http,_,_ = management
    assert http.get('/api/remote-connect/rustdesk/settings',headers={'Host':'bad.example:8788'}).status_code == 400
    assert http.get('/api/remote-connect/rustdesk/settings',headers={'Origin':'http://bad.example:8788'}).status_code == 403
    assert http.post('/api/remote-connect/rustdesk/autostart',json={'enabled':True},headers={'X-ORH-Request':''}).status_code == 403
    access.create('viewer-fixture','viewer',time.time()+300)
    http.cookies.set('orh','viewer-fixture')
    assert http.get('/api/remote-connect').status_code == 403
    http.cookies.clear()
    assert http.get('/api/remote-connect').status_code == 401
    assert http.get('/').status_code == 200


def test_native_lifecycle_and_autostart(management):
    http,native,_ = management
    assert http.post('/api/remote-connect/rustdesk/service',json={'action':'stop'}).status_code == 400
    assert http.post('/api/remote-connect/rustdesk/service',json={'action':'stop','confirm':True}).status_code == 200
    assert native.values['stop-service'] == 'Y'
    assert http.post('/api/remote-connect/rustdesk/service',json={'action':'start'}).status_code == 200
    assert native.values.get('stop-service','') == ''
    assert http.post('/api/remote-connect/rustdesk/service',json={'action':'restart','confirm':True}).status_code == 200
    assert native.values.get('stop-service','') == ''
    assert http.post('/api/remote-connect/rustdesk/service',json={'action':'shell'}).status_code == 400
    assert http.post('/api/remote-connect/rustdesk/autostart',json={'enabled':True}).json() == {'enabled':True}
    assert client.autostart()


def test_password_in_memory_and_validation_redaction(management):
    http,native,audit = management
    password = 'fixture-long-private-password'
    assert http.post('/api/remote-connect/rustdesk/password',json={'password':password}).json() == {'ok':True}
    assert native.password == password
    assert all(password not in str(entry) for entry in audit)
    response = http.post('/api/remote-connect/rustdesk/password',json={'password':password*100})
    assert response.status_code == 400
    assert password not in response.text
    assert http.post('/api/remote-connect/rustdesk/password/temporary',json={}).json() == {'password':'fixture-secret'}
    assert list(client.data_dir().iterdir()) == []


@pytest.mark.parametrize('key,value',[
    ('unknown','Y'),('enable-keyboard','yes'),('key','bad\nvalue'),('direct-access-port','0'),
    ('direct-access-port','99999'),('approve-mode','shell'),('api-server','file:///etc/passwd'),
])
def test_option_boundary(key,value):
    with pytest.raises(ValueError):client.validate(key,value)


def test_connection_argv_and_injection_rejection(management,monkeypatch):
    http,_,_ = management
    calls=[]
    monkeypatch.setattr(client.subprocess,'Popen',lambda argv,**kwargs:calls.append(argv))
    assert http.post('/api/remote-connect/rustdesk/connect',json={'target':'123 456 789','mode':'desktop'}).status_code == 200
    assert calls[-1] == [str(client.BINARY),'--connect','123456789']
    assert http.post('/api/remote-connect/rustdesk/connect',json={'target':'192.168.1.20:21118','mode':'files'}).status_code == 200
    assert calls[-1][-2:] == ['--file-transfer','192.168.1.20:21118']
    for target in ('--password','123;touch /tmp/oops','$(id)','a\nb',''):
        assert http.post('/api/remote-connect/rustdesk/connect',json={'target':target}).status_code in (400,422)
    assert len(calls) == 2


@pytest.mark.parametrize('length',[1,63,64,16383,16384,20000])
def test_codec_fragmented_reads(length):
    left,right=socket.socketpair()
    value={'t':'Options','c':{'key':'中'*length}}
    encoded=ipc.frame(value)
    def send():
        try:
            for offset in range(0,len(encoded),37):right.sendall(encoded[offset:offset+37])
        finally:right.close()
    worker=threading.Thread(target=send);worker.start()
    try:assert ipc.receive(left) == value
    finally:left.close();worker.join()


def test_real_unix_socket_read_write_and_ack():
    directory=tempfile.TemporaryDirectory(prefix='rdl-',dir='/tmp')
    path=Path(directory.name)/'ipc';server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
    server.bind(str(path));server.listen()
    captured=[]
    def accept():
        connection,_=server.accept()
        with connection:
            captured.append(ipc.receive(connection))
            connection.sendall(ipc.frame({'t':'Config','c':['permanent-password','Y']}))
    worker=threading.Thread(target=accept);worker.start()
    try:
        ipc.Native(path).set_password('fixture-in-memory')
        worker.join()
        assert captured == [{'t':'Config','c':['permanent-password','fixture-in-memory']}]
    finally:server.close();directory.cleanup()


def test_start_reuses_existing_native_without_spawning(management,monkeypatch):
    monkeypatch.setattr(client.subprocess,'Popen',lambda *args,**kwargs:pytest.fail('must reuse native client'))
    assert client.start() == {'reused':True}


def test_missing_or_invalid_socket(tmp_path):
    with pytest.raises(ipc.NativeError):ipc.Native(tmp_path/'missing').config('id')
    (tmp_path/'file').write_text('not a socket')
    with pytest.raises(ipc.NativeError):ipc.Native(tmp_path/'file').config('id')


def test_app_translocation_process_discovery(monkeypatch):
    monkeypatch.setattr(client,'BINARY',Path('/Applications/RustDesk.app/Contents/MacOS/RustDesk'))
    from types import SimpleNamespace
    import os
    class Process:
        info={'name':'RustDesk'}
        pid=321
        def exe(self):return '/private/tmp/AppTranslocation/test/d/RustDesk.app/Contents/MacOS/RustDesk'
        def uids(self):return SimpleNamespace(real=os.getuid())
        def cmdline(self):return [self.exe()]
        def create_time(self):return 100
    monkeypatch.setattr(client.psutil,'process_iter',lambda attrs:[Process()])
    assert client.processes() == [dict(pid=321,created=100,background=False)]


def test_background_start_uses_native_server_argv(management,monkeypatch):
    class OfflineNative:
        def config(self,name):raise ipc.NativeError('offline')
    monkeypatch.setattr(client,'native',OfflineNative())
    binary=client.data_dir()/'RustDesk';binary.write_text('fixture')
    monkeypatch.setattr(client,'BINARY',binary)
    calls=[]
    monkeypatch.setattr(client.subprocess,'Popen',lambda argv,**kwargs:calls.append(argv))
    assert client.start() == {'reused':False}
    assert calls == [[str(client.BINARY),'--server']]


def test_tailscale_control_ack_and_diag_routes(management,monkeypatch):
    http,_,_=management
    calls=[]
    monkeypatch.setattr(tailscale,'operation',None)
    monkeypatch.setattr(tailscale,'command',lambda args,**kwargs:calls.append(args) or 'native diagnostic result')
    assert http.post('/api/remote-connect/tailscale/control',json={'action':'disconnect'}).status_code==400
    response=http.post('/api/remote-connect/tailscale/control',json={'action':'disconnect','confirm':True})
    assert response.status_code==202 and response.json()['state']=='pending'
    assert calls==[['down','--accept-risk=lose-ssh']]
    assert tailscale.operation['state']=='done'
    assert http.post('/api/remote-connect/tailscale/netcheck',json={}).json()=={'output':'native diagnostic result'}
