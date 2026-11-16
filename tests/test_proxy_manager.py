"""No live routes or subscription secrets are used by this suite."""
from test_files import workspace
import copy
import importlib.util
import json
from pathlib import Path
import time
import httpx
import pytest
from fastapi import HTTPException
from app import access,proxy_manager as manager

spec=importlib.util.spec_from_file_location('proxy_engine',Path(__file__).resolve().parents[1]/'scripts/proxy_engine.py')
engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)
SOURCE={'proxies':[{'name':'fixture','type':'direct'}],'proxy-groups':[{'name':'PROXY','type':'select','proxies':['fixture']}],'rules':['MATCH,PROXY']}


@pytest.fixture
def profiles(workspace,monkeypatch):
    client,_,_=workspace
    monkeypatch.setattr(manager,'default_socket',lambda:None)
    state={'ready':True,'enabled':False,'privileged':True,'network_revision':2,'revision':'initial','config_revision':engine.digest({})}
    mutations=[]
    async def call(method,path,body=None):
        if path=='/orh/state':return dict(state)
        if path=='/orh/validate':
            engine.normalize(body['source'],Path('/fixture'),'private')
            return {'ok':True}
        if path=='/orh/control':
            if body['revision']!=state['revision']:raise HTTPException(409,'stale')
            mutations.append(copy.deepcopy(body))
            if body['action']=='apply':state['config_revision']=engine.digest(body['source'])
            else:state['enabled']=body['action']=='enable'
            state['revision']=str(time.time_ns());return dict(state)
        raise AssertionError(path)
    monkeypatch.setattr(manager,'call',call)
    return client,state,mutations


def imported(c,name='机场 <test>'):
    r=c.post('/api/proxy/manager/import',json={'name':name,'text':json.dumps(SOURCE)})
    assert r.status_code==200,r.text
    return r.json()


def test_profile_lifecycle_validation_conflict_and_recovery(profiles):
    c,state,mutations=profiles
    row=imported(c)
    assert not row['active'] and row['nodes']==1 and not mutations
    args=dict(action='activate',id=row['id'],revision=row['revision'],confirm=row['name'])
    assert c.post('/api/proxy/manager/profile',json={**args,'confirm':''}).status_code==200
    assert len(mutations)==1 and state['config_revision']==engine.digest(SOURCE)
    assert c.get('/api/proxy/manager').json()['consistent']
    state['enabled']=True
    assert c.post('/api/proxy/manager/profile',json={**args,'action':'delete'}).status_code==409
    state['enabled']=False
    detail=c.get('/api/proxy/manager/profile/'+row['id']).json()
    assert 'fixture' in detail['text']
    assert c.post('/api/proxy/manager/profile',json={**args,'action':'save','text':'bad'}).status_code==422
    assert len(mutations)==1
    assert c.post('/api/proxy/manager/profile',json={**args,'action':'rename','name':'new'}).status_code==200
    assert c.post('/api/proxy/manager/profile',json=args).status_code==409
    other=imported(c,'other')
    remove=dict(action='delete',id=other['id'],revision=other['revision'],confirm=other['name'])
    assert c.post('/api/proxy/manager/profile',json=remove).status_code==200
    assert (manager.root()/'trash'/(other['id']+'.json')).exists()
    assert (manager.root()/'profiles.json').stat().st_mode&0o777==0o600
    current=c.get('/api/proxy/manager').json()['profiles'][0]
    assert c.post('/api/proxy/manager/profile',json=dict(action='delete',id=current['id'],revision=current['revision'],confirm=current['name'])).status_code==200
    assert not c.get('/api/proxy/manager').json()['profiles']
    assert mutations[-1]['source']=={},'Stopped current profile can be removed without importing a replacement'


def test_subscription_credentials_not_returned_and_failed_update_keeps_old(profiles,monkeypatch):
    c,_,_=profiles
    async def download(url):return json.dumps(SOURCE),{'total':100,'download':20}
    monkeypatch.setattr(manager,'download',download)
    url='https://example.invalid/api?token=PRIVATE_SUBSCRIPTION'
    result=c.post('/api/proxy/manager/import',json={'name':'sub','url':url})
    assert result.status_code==200
    assert 'PRIVATE_SUBSCRIPTION' not in result.text+c.get('/api/proxy/manager').text
    row=result.json();before=(manager.root()/'profiles.json').read_text()
    async def failed(url):raise HTTPException(502,'下载失败')
    monkeypatch.setattr(manager,'download',failed)
    r=c.post('/api/proxy/manager/profile',json={'action':'update','id':row['id'],'revision':row['revision']})
    assert r.status_code==502 and (manager.root()/'profiles.json').read_text()==before


def test_proxy_auth_sensitive_exports_and_service_confirmation(profiles,monkeypatch):
    c,_,_=profiles;row=imported(c)
    assert c.post('/api/proxy/manager/service',json={'action':'enable','revision':'initial'}).status_code==409
    assert c.post('/api/proxy/manager/service',json={'action':'disable','revision':'initial'}).status_code==400
    previous=manager.call;closed=[]
    async def controlled(method,path,body=None):
        if method=='DELETE':closed.append(path);return {}
        return await previous(method,path,body)
    monkeypatch.setattr(manager,'call',controlled)
    assert c.post('/api/proxy/manager/connections/close',json={'id':'valid-id','confirm':''}).status_code==400
    assert c.post('/api/proxy/manager/connections/close',json={'id':'../configs','confirm':'../configs'}).status_code==422
    assert not closed
    assert c.post('/api/proxy/manager/connections/close',json={'id':'valid-id','confirm':'valid-id'}).status_code==200
    assert closed==['/connections/valid-id']
    c.post('/api/logout',json={})
    assert c.get('/api/proxy/manager').status_code==401
    token='proxy-manager-viewer';access.create(token,'viewer',time.time()+60);c.cookies.set('orh',token)
    assert c.get('/api/proxy/manager').status_code==200
    assert c.get('/api/proxy/manager/profile/'+row['id']).status_code==403
    assert c.get('/api/proxy/manager/profile/'+row['id']+'/download').status_code==403
    assert c.post('/api/proxy/manager/import',json={'name':'x','text':json.dumps(SOURCE)}).status_code==403


def test_yaml_alias_custom_types_and_bad_shapes_are_rejected():
    for text in ('!!python/object/apply:os.system [echo unsafe]','proxies: &nodes [*nodes]','proxies: []','[1, 2]','proxies: 2024-01-01'):
        with pytest.raises(HTTPException):manager.parse(text)


def test_subscription_ssrf_and_redirect_pinning(monkeypatch):
    import asyncio
    monkeypatch.setattr(manager.socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('127.0.0.1',443))])
    for url in ('https://localhost/private','http://127.0.0.1:8765','http://100.66.1.2','file:///etc/passwd','https://user:secret@example.com'):
        with pytest.raises(HTTPException):asyncio.run(manager.download(url))


def test_fake_ip_resolves_real_public_ip_and_rechecks_redirect(monkeypatch):
    import asyncio
    actual=httpx.AsyncClient;seen=[]
    monkeypatch.setattr(manager.socket,'getaddrinfo',lambda host,*a,**k:[(2,1,6,'',('127.0.0.1' if host=='localhost' else '198.18.1.2',443))])
    def backend(request):
        seen.append(request)
        if request.url.host=='1.1.1.1':return httpx.Response(200,json={'Answer':[{'type':1,'data':'93.184.216.34'}]})
        assert request.url.host=='93.184.216.34' and request.headers['Host']=='example.invalid'
        assert request.extensions['sni_hostname']=='example.invalid'
        return httpx.Response(302,headers={'Location':'http://localhost/private'})
    monkeypatch.setattr(manager.httpx,'AsyncClient',lambda **kw:actual(transport=httpx.MockTransport(backend),**kw))
    with pytest.raises(HTTPException):asyncio.run(manager.download('https://example.invalid/private-token'))
    assert len(seen)==2 and not any(r.url.host=='127.0.0.1' for r in seen)


def test_engine_normalizer_owns_listeners_routes_and_provider_paths(tmp_path):
    src={**copy.deepcopy(SOURCE),'listeners':[{'port':9000}],'external-controller':'0.0.0.0:9999','secret':'PRIVATE','tun':{'enable':True},'dns':{'enable':False,'listen':'0.0.0.0:53'},'proxy-providers':{'a':{'type':'http','url':'https://example.invalid/token','path':'/etc/passwd'}}}
    result=engine.normalize(src,tmp_path,'fixed-secret')
    assert result['tun']['dns-mode']=='native'
    assert not result['tun']['enable'] and result['external-controller']=='127.0.0.1:19090'
    assert result['secret']=='fixed-secret' and result['allow-lan'] is False and 'listeners' not in result
    assert result['dns']['listen']=='127.0.0.1:1054'
    assert '100.64.0.0/10' in result['tun']['route-exclude-address']
    assert result['proxy-providers']['a']['path'].startswith(str(tmp_path/'providers'))
    assert src['tun']['enable'] and src['secret']=='PRIVATE','never mutate imported source'
    with pytest.raises(ValueError):engine.normalize({**SOURCE,'proxy-providers':{'x':{'type':'file','path':'/etc/passwd'}}},tmp_path,'x')


def test_engine_enable_conflict_privilege_and_stale_guard(monkeypatch,tmp_path):
    obj=engine.Engine.__new__(engine.Engine);obj.home=tmp_path;obj.state={'source':SOURCE,'enabled':False,'mode':'rule'}
    obj.status=lambda:{'configured':True};obj.state_path=tmp_path/'state.json'
    monkeypatch.setattr(engine.os,'geteuid',lambda:501)
    args={'action':'enable','revision':engine.digest(obj.state)}
    with pytest.raises(ValueError,match='管理员'):obj.change(args)
    monkeypatch.setattr(engine.os,'geteuid',lambda:0)
    monkeypatch.setattr(engine,'clash_connected',lambda:True)
    with pytest.raises(ValueError,match='Clash'):obj.change(args)
    assert not obj.state['enabled']
    with pytest.raises(ValueError,match='状态已变化'):obj.change({**args,'revision':'stale'})


def fake_engine(tmp_path):
    from types import SimpleNamespace
    obj=engine.Engine.__new__(engine.Engine);obj.home=tmp_path;obj.secret='private';obj.binary=Path('/fixture/mihomo')
    obj.state={'source':copy.deepcopy(SOURCE),'enabled':False,'mode':'rule'};obj.state_path=tmp_path/'state.json'
    obj.process=SimpleNamespace(poll=lambda:None,pid=123)
    return obj


def test_emergency_stop_never_waits_on_validation_or_subscription(monkeypatch,tmp_path):
    obj=fake_engine(tmp_path);obj.state['enabled']=True;calls=[]
    def core(method,path,data=None):
        calls.append((method,path,data));return {'tun':{'enable':False}}
    obj.core=core
    monkeypatch.setattr(engine.subprocess,'run',lambda *a,**k:pytest.fail('Emergency stop must not run config validation'))
    result=obj.change({'action':'disable','revision':engine.digest(obj.state)})
    assert not result['enabled'] and calls[0]==('PATCH','/configs',{'tun':{'enable':False}})
    assert not json.loads(obj.state_path.read_text())['enabled']


def test_failed_candidate_validation_does_not_reload_running_core(monkeypatch,tmp_path):
    from types import SimpleNamespace
    obj=fake_engine(tmp_path);before=copy.deepcopy(obj.state);obj.core=lambda *a,**k:pytest.fail('Bad validation must not reload existing connections')
    monkeypatch.setattr(engine.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1))
    with pytest.raises(ValueError,match='配置检查失败'):obj.change({'action':'apply','source':{**SOURCE,'mode':'global'},'revision':engine.digest(obj.state)})
    assert obj.state==before and not (tmp_path/'candidate.json').exists()


def test_failed_reload_attempts_previous_config_rollback(monkeypatch,tmp_path):
    from types import SimpleNamespace
    obj=fake_engine(tmp_path);before=copy.deepcopy(obj.state);calls=[]
    def core(method,path,data=None):
        calls.append(data)
        if len(calls)==1:raise ValueError('rejected candidate')
        return {}
    obj.core=core
    monkeypatch.setattr(engine.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0))
    with pytest.raises(ValueError,match='rejected candidate'):obj.change({'action':'apply','source':{**SOURCE,'rules':['MATCH,DIRECT']},'revision':engine.digest(obj.state)})
    assert obj.state==before and len(calls)==2
    assert json.loads(calls[1]['payload'])['rules'][-1]=='MATCH,PROXY'


def test_existing_broker_is_discovered_and_explicit_settings_take_precedence(workspace,monkeypatch,tmp_path):
    socket=tmp_path/'broker.sock';socket.touch()
    monkeypatch.setattr(manager,'default_socket',lambda:socket)
    assert manager.settings()=={'socket':str(socket)}
    manager.atomic(manager.root()/'connection.json',{'socket':'/custom/broker.sock'})
    assert manager.settings()=={'socket':'/custom/broker.sock'}


def test_install_keeps_existing_current_broker(profiles,monkeypatch):
    from app import main
    c,_,_=profiles
    monkeypatch.setattr(manager.sys,'platform','darwin')
    monkeypatch.setattr(main,'task_create',lambda body:pytest.fail('Existing broker must keep running'))
    assert c.post('/api/proxy/manager/install',json={}).json()=={'installed':True}


def test_install_starts_packaged_setup_through_task_runner(profiles,monkeypatch):
    from app import main,launcher
    c,state,_=profiles;state.update(ready=False,privileged=False)
    monkeypatch.setattr(manager.sys,'platform','darwin')
    monkeypatch.setattr(launcher,'command',lambda *args:['/Applications/OpenRemoteHub.app/Contents/MacOS/OpenRemoteHub',*args])
    created=[];started=[]
    monkeypatch.setattr(main,'task_create',lambda body:created.append(body) or {'id':'installer'})
    monkeypatch.setattr(main,'task_action',lambda key,body:started.append((key,body.action)))
    response=c.post('/api/proxy/manager/install',json={})
    assert response.status_code==200,response.text
    assert started==[('installer','start')]
    assert created[0].argv[1:5]==['--run-script','proxy_setup.py','setup','--authorize']
    assert created[0].argv[-2:]==['--data-dir',str(manager.root())]
    assert json.loads((manager.root()/'installation.json').read_text())=={'task_id':'installer'}


def test_packaged_proxy_installer_uses_native_authorization_and_root_owned_runtime(monkeypatch,tmp_path):
    spec=importlib.util.spec_from_file_location('proxy_setup',Path(__file__).resolve().parents[1]/'scripts/proxy_setup.py')
    setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)
    executable=tmp_path/'OpenRemoteHub.app/Contents/MacOS/OpenRemoteHub'
    executable.parent.mkdir(parents=True);executable.write_text('binary')
    monkeypatch.setattr(setup.sys,'frozen',True,raising=False)
    monkeypatch.setattr(setup.sys,'platform','darwin')
    monkeypatch.setattr(setup.sys,'executable',str(executable))
    monkeypatch.setattr(setup,'DATA',tmp_path/'user data')
    calls=[];monkeypatch.setattr(setup,'run',calls.append)
    setup.authorize('fixture-user')
    assert calls[0][:2]==['/usr/bin/osascript','-e']
    assert 'with administrator privileges' in calls[0][2]
    assert '--run-script proxy_setup.py install --owner fixture-user' in calls[0][2]
    home=tmp_path/'system service';home.mkdir()
    command=setup.install_runtime(home)
    assert command==[str(home/'runtime/OpenRemoteHub.app/Contents/MacOS/OpenRemoteHub'),'--run-script','proxy_engine.py']
    assert Path(command[0]).read_text()=='binary'
    assert setup.owned_service(command,home)
    assert setup.owned_service(['/usr/bin/python3',str(home/'proxy_engine.py')],home)


def test_installer_downloads_baseline_x64_build(monkeypatch,tmp_path):
    import gzip
    import hashlib
    import io
    spec=importlib.util.spec_from_file_location('proxy_setup_download',Path(__file__).resolve().parents[1]/'scripts/proxy_setup.py')
    setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)
    monkeypatch.setattr(setup,'DATA',tmp_path)
    monkeypatch.setattr(setup.platform,'machine',lambda:'x86_64')
    monkeypatch.setattr(setup.platform,'system',lambda:'Linux')
    archive=gzip.compress(b'baseline-core')
    release={'tag_name':'vfixture','html_url':'https://github.com/MetaCubeX/mihomo/releases/tag/vfixture','assets':[
        {'name':'mihomo-linux-amd64-v1-vfixture.gz','browser_download_url':'https://fixture/baseline','digest':'sha256:'+hashlib.sha256(archive).hexdigest()},
        {'name':'mihomo-linux-amd64-vfixture.gz','browser_download_url':'https://fixture/v3'}]}
    def response(url,**kwargs):
        return io.BytesIO(json.dumps(release).encode() if not isinstance(url,str) else archive if url.endswith('/baseline') else pytest.fail('Must select baseline CPU support'))
    monkeypatch.setattr(setup.urllib.request,'urlopen',response)
    setup.download()
    assert (tmp_path/'bin/mihomo').read_bytes()==b'baseline-core'
    assert json.loads((tmp_path/'bin/release.json').read_text())['asset']=='mihomo-linux-amd64-v1-vfixture.gz'
