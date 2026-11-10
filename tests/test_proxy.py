from test_files import workspace
import copy
import time
from pathlib import Path
import httpx
import pytest
from app import access,proxy
from app.platforms import MacHost


@pytest.fixture
def proxy_client(workspace,monkeypatch):
    c,_,_=workspace
    state={'mode':'rule','groups':{'策略 / #中文':{'type':'Selector','now':'first','all':['first','second']},'automatic':{'type':'URLTest','now':'first','all':['first','second']},'first':{'type':'Direct'},'second':{'type':'Shadowsocks'}}}
    calls=[]
    def backend(request):
        import json
        calls.append((request.method,request.url.raw_path))
        path=request.url.path
        if path=='/version':return httpx.Response(200,json={'version':'fixture-core'})
        if path=='/configs':
            if request.method=='PATCH':state['mode']=json.loads(request.content)['mode']
            return httpx.Response(200,json={'mode':state['mode'],'secret':'MUST_NOT_LEAK','authentication':['SECRET_AUTH'],'tun':{'enable':True}})
        if path=='/proxies':return httpx.Response(200,json={'proxies':copy.deepcopy(state['groups'])})
        if path.endswith('/delay'):return httpx.Response(200,json={'delay':42})
        if path.startswith('/proxies/'):
            name=path[len('/proxies/'):]
            if request.method=='PUT':state['groups'][name]['now']=json.loads(request.content)['name']
            return httpx.Response(200,json=copy.deepcopy(state['groups'][name]))
        if path=='/connections':return httpx.Response(200,json={'uploadTotal':20,'downloadTotal':30,'memory':40,'connections':[{'metadata':{'host':'example.invalid','destinationPort':'443','network':'tcp','process':'fixture','inboundUser':'MUST_NOT_LEAK'},'chains':['first'],'rule':'MATCH','upload':10,'download':20}]})
        raise AssertionError('Unexpected controller request '+str(request.url))
    monkeypatch.setattr(proxy,'controller',lambda:httpx.AsyncClient(base_url='http://local',transport=httpx.MockTransport(backend)))
    monkeypatch.setattr(proxy.host,'proxy_status',lambda:dict(platform='fixture',proxies=[],vpn=None))
    return c,state,calls


def test_proxy_snapshot_sanitizes_private_controller_fields(proxy_client):
    c,_,_=proxy_client
    response=c.get('/api/proxy');assert response.status_code==200
    data=response.json()
    assert data['available'] and data['mode']=='rule' and data['tun_enabled']
    assert len(data['groups'])==2 and data['connection_count']==1 and data['node_count']==4
    assert 'MUST_NOT_LEAK' not in response.text and 'SECRET_AUTH' not in response.text
    result=c.get('/api/proxy/connections')
    assert result.json()['entries'][0]['host']=='example.invalid'
    assert 'MUST_NOT_LEAK' not in result.text


def test_proxy_changes_require_confirmation_membership_and_current_revision(proxy_client):
    c,state,calls=proxy_client
    snapshot=c.get('/api/proxy').json()
    mode=dict(action='mode',value='global',revision=snapshot['revision'],confirm='mode')
    assert c.post('/api/proxy/control',json={**mode,'confirm':''}).status_code==400
    assert c.post('/api/proxy/control',json={**mode,'value':'invalid'}).status_code==400
    assert state['mode']=='rule'
    assert c.post('/api/proxy/control',json=mode).status_code==200 and state['mode']=='global'
    assert c.post('/api/proxy/control',json=mode).status_code==409
    group=next(g for g in snapshot['groups'] if g['type']=='Selector')
    select=dict(action='select',target=group['name'],value='second',revision=group['revision'],confirm=group['name'])
    assert c.post('/api/proxy/control',json={**select,'value':'unknown'}).status_code==400
    assert c.post('/api/proxy/control',json=select).status_code==200
    assert state['groups'][group['name']]['now']=='second'
    assert c.post('/api/proxy/control',json=select).status_code==409
    automatic=next(g for g in snapshot['groups'] if g['type']=='URLTest')
    assert c.post('/api/proxy/control',json={**select,'target':automatic['name'],'confirm':automatic['name'],'revision':automatic['revision']}).status_code==400
    assert any(b'%2F' in path and method=='PUT' for method,path in calls)


def test_proxy_delay_does_not_switch_nodes_and_auth_guards(proxy_client):
    c,state,calls=proxy_client;before=copy.deepcopy(state)
    result=c.post('/api/proxy/delay',json={'name':'first'})
    assert result.status_code==200 and result.json()['delay']==42
    assert before==state and not any(method in ('PATCH','PUT') for method,_ in calls)
    assert c.post('/api/proxy/delay',json={'name':'unknown'}).status_code==404
    c.post('/api/logout',json={})
    assert c.get('/api/proxy').status_code==401
    token='proxy-viewer';access.create(token,'viewer',time.time()+60);c.cookies.set('orh',token)
    assert c.get('/api/proxy').status_code==200
    assert c.post('/api/proxy/delay',json={'name':'first'}).status_code==403
    assert c.post('/api/proxy/control',json=dict(action='mode',value='global',revision='',confirm='mode')).status_code==403
    assert c.get('/api/proxy',headers={'Origin':'https://evil.test'}).status_code==403


def test_proxy_disconnect_and_bad_response_are_explicit(proxy_client,monkeypatch):
    c,_,_=proxy_client
    monkeypatch.setattr(proxy,'controller',lambda:httpx.AsyncClient(base_url='http://local',transport=httpx.MockTransport(lambda request:httpx.Response(403,text='PRIVATE_SECRET'))))
    response=c.get('/api/proxy')
    assert response.status_code==200 and not response.json()['available']
    assert 'PRIVATE_SECRET' not in response.text
    monkeypatch.setattr(proxy,'controller',lambda:httpx.AsyncClient(base_url='http://local',transport=httpx.MockTransport(lambda request:httpx.Response(200,json=['bad format']))))
    assert not c.get('/api/proxy').json()['available']


def test_mac_proxy_adapter_distinguishes_tun_and_system_proxy(monkeypatch):
    import app.platforms as platforms
    monkeypatch.setattr(platforms,'command',lambda args,timeout:'<dictionary> {\n HTTPEnable : 0\n SOCKSEnable : 0\n}' if args[-1]=='--proxy' else '* (Connected) UUID VPN (com.hako.network) "Clash" [VPN:com.hako.network]')
    result=MacHost().proxy_status()
    assert result['vpn']['state']=='Connected'
    assert all(not row['enabled'] for row in result['proxies'])


def test_controller_settings_restrict_browser_unrelated_targets(monkeypatch,tmp_path):
    from fastapi import HTTPException
    monkeypatch.setenv('ORH_CLASH_SOCKET','')
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:tmp_path))
    for address in ('http://example.invalid:9090','http://192.168.1.1:9090','http://user:password@127.0.0.1:9090','http://127.0.0.1:9090/private','http://127.0.0.1:9090?secret=value'):
        monkeypatch.setenv('ORH_CLASH_URL',address)
        with pytest.raises(HTTPException):proxy.controller()
