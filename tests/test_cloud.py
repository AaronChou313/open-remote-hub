"""Account isolation, binding ownership, one-use tickets and Agent sessions."""
import concurrent.futures
import json
from pathlib import Path
import secrets
import sys
import time
from urllib.parse import parse_qs, urlsplit
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest
from cloud.main import app as cloud_app
from cloud.store import database, digest
from app import main, cloud_agent, access, native_terminal, passwords
from app.network import Network


@pytest.fixture
def cloud(tmp_path,monkeypatch):
    monkeypatch.setenv('ORH_CLOUD_DATA',str(tmp_path/'cloud'))
    monkeypatch.setenv('ORH_CLOUD_ORIGINS','http://testserver,https://aaronchou313.github.io')
    with TestClient(cloud_app) as client:
        yield client


def signup(cloud,name):
    response = cloud.post('/api/register',json={'username':name,'password':'test-password-42'})
    assert response.status_code==200,response.text
    value=response.json()
    return {'Authorization':'Bearer '+value['token']},value['user']


def bind_device(cloud,headers,identifier=None):
    metadata=dict(instance_id=identifier or str(uuid.uuid4()),name='Mac mini',os='Darwin',addresses=['http://100.66.11.2:8765','http://192.168.1.20:8765'],port=8765)
    start=cloud.post('/agent/bindings/start',json=metadata)
    assert start.status_code==200,start.text
    pending=start.json()
    assert cloud.post('/api/bindings/approve',headers=headers,json={'code':pending['user_code']}).status_code==200
    device_headers={'Authorization':'Bearer '+pending['device_code']}
    assert cloud.post('/agent/heartbeat',headers=device_headers,json=metadata).status_code==200
    return metadata,device_headers,pending


def ticket(cloud,headers,metadata,state=''):
    response=cloud.post('/api/devices/'+metadata['instance_id']+'/ticket',headers=headers,json={'address':metadata['addresses'][0],'state':state})
    assert response.status_code==200,response.text
    return parse_qs(urlsplit(response.json()['url']).fragment)['ticket'][0]


def test_account_isolation_and_binding(cloud):
    first,owner=signup(cloud,'owner-one')
    second,_=signup(cloud,'owner-two')
    metadata,device,pending=bind_device(cloud,first)
    identifier=metadata['instance_id']
    assert cloud.get('/api/devices',headers=second).json()==[]
    rows=cloud.get('/api/devices',headers=first).json()
    assert len(rows)==1 and rows[0]['online']
    assert 'credential_hash' not in rows[0] and 'owner_id' not in rows[0]
    for method,path,body in [('patch','',{'name':'stolen'}),('delete','',None),('post','/ticket',{'address':metadata['addresses'][0]})]:
        response=getattr(cloud,method)('/api/devices/'+identifier+path,headers=second,**({'json':body} if body else {}))
        assert response.status_code==404
    assert cloud.post('/api/bindings/approve',headers=second,json={'code':pending['user_code']}).status_code==404
    assert cloud.get('/api/bindings/'+pending['user_code'],headers=second).status_code==404
    assert cloud.post('/agent/heartbeat',headers=device,json={**metadata,'instance_id':str(uuid.uuid4())}).status_code==403
    assert cloud.get('/api/devices').status_code==401


def test_tickets_single_use_wrong_device_expiry_and_logout(cloud):
    headers,_=signup(cloud,'ticket-owner')
    first,agent,_=bind_device(cloud,headers)
    second,other,_=bind_device(cloud,headers)
    value=ticket(cloud,headers,first)
    assert cloud.post('/agent/tickets/redeem',headers=other,json={'ticket':value}).status_code==401
    def redeem():return cloud.post('/agent/tickets/redeem',headers=agent,json={'ticket':value}).status_code
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _:redeem(),range(2)))==[200,401]
    expired=ticket(cloud,headers,first)
    with database() as db:db.execute('UPDATE tickets SET expires=0 WHERE digest=?',(digest(expired),))
    assert cloud.post('/agent/tickets/redeem',headers=agent,json={'ticket':expired}).status_code==401
    pending=ticket(cloud,headers,first)
    assert cloud.post('/api/logout',headers=headers,json={}).status_code==200
    assert cloud.post('/agent/tickets/redeem',headers=agent,json={'ticket':pending}).status_code==401


def test_address_sync_preference_and_unbind(cloud):
    headers,_=signup(cloud,'address-owner')
    metadata,agent,_=bind_device(cloud,headers)
    key=metadata['instance_id']
    manual='https://mac.example.com'
    assert cloud.patch('/api/devices/'+key,headers=headers,json={'name':'My Mac','addresses':[manual,metadata['addresses'][0]],'preferred':manual}).status_code==200
    assert cloud.post('/agent/heartbeat',headers=agent,json={**metadata,'addresses':metadata['addresses']+['http://10.77.1.2:8765']}).status_code==200
    row=cloud.get('/api/devices',headers=headers).json()[0]
    assert row['name']=='My Mac' and row['preferred']==manual
    assert metadata['addresses'][1] not in row['addresses']
    assert 'http://10.77.1.2:8765' in row['addresses'] and manual in row['addresses']
    assert cloud.post('/api/devices/'+key+'/ticket',headers=headers,json={'address':'https://evil.example'}).status_code==422
    assert cloud.patch('/api/devices/'+key,headers=headers,json={'addresses':['javascript://evil']}).status_code==422
    value=ticket(cloud,headers,metadata)
    assert cloud.delete('/api/devices/'+key,headers=headers).status_code==200
    assert cloud.post('/agent/heartbeat',headers=agent,json=metadata).status_code==401
    assert cloud.post('/agent/tickets/redeem',headers=agent,json={'ticket':value}).status_code==401


def test_agent_cookie_api_terminal_and_restart(cloud,tmp_path,monkeypatch):
    owner,user=signup(cloud,'agent-owner')
    metadata,device,pending=bind_device(cloud,owner)
    monkeypatch.setattr(main,'DATA',tmp_path/'agent')
    main.DATA.mkdir()
    monkeypatch.setattr(main,'NETWORK',Network('0.0.0.0',frozenset(['100.66.11.2','127.0.0.1','localhost'])))
    cloud_agent.save(dict(status='bound',cloud_url='https://cloud.example',credential=pending['device_code'],owner_id=user['id'],username=user['username'],instance_id=metadata['instance_id']))
    def call(base,path,body,credential=None):
        response=cloud.post(path,json=body,headers={'Authorization':'Bearer '+credential} if credential else {})
        if response.status_code>=400:
            from fastapi import HTTPException
            raise HTTPException(response.status_code,response.json()['detail'])
        return response.json()
    monkeypatch.setattr(cloud_agent,'call',call)
    assert passwords.record() is None
    origin='http://100.66.11.2:8765'
    agent_client=TestClient(main.app,base_url=origin,headers={'Origin':origin,'X-ORH-Request':'1'})
    assert agent_client.get('/api/auth/status').json()['needs_setup'] is False
    assert agent_client.post('/api/login',json={'password':'anything'}).status_code==409
    value=ticket(cloud,owner,metadata)
    assert agent_client.post('/auth/cloud/exchange',json={'ticket':value,'state':''}).status_code==200
    cookie=agent_client.cookies.get('orh')
    assert access.get(cookie)['role']=='admin'
    assert agent_client.get('/api/me').status_code==200
    assert agent_client.get('/terminal/open/demo').status_code==200
    assert native_terminal.admin(cookie)
    assert agent_client.post('/auth/cloud/exchange',json={'ticket':value}).status_code==401
    # A new client after Agent restart can use the same durable cookie and binding.
    other_client=TestClient(main.app,base_url=origin)
    other_client.cookies.set('orh',cookie)
    assert other_client.get('/api/me').status_code==200
    reached=[]
    async def upstream():
        reached.append(True)
        raise RuntimeError('isolated gateway test')
    monkeypatch.setattr(native_terminal.upstream,'authenticate',upstream)
    with pytest.raises(WebSocketDisconnect):
        with agent_client.websocket_connect(origin.replace('http:','ws:')+'/terminal/ws/control?web_client_id=test'):pass
    assert reached
    cloud_agent.save({'status':'revoked','cloud_url':'https://cloud.example'})
    assert access.get(cookie) is None
    assert agent_client.get('/api/me').status_code==401


def test_direct_agent_authorization_state(cloud,tmp_path,monkeypatch):
    headers,user=signup(cloud,'direct-owner')
    metadata,device,pending=bind_device(cloud,headers)
    monkeypatch.setattr(main,'DATA',tmp_path/'direct-agent');main.DATA.mkdir()
    monkeypatch.setattr(main,'NETWORK',Network('0.0.0.0',frozenset(['100.66.11.2'])))
    cloud_agent.save(dict(status='bound',cloud_url='https://cloud.example',credential=pending['device_code'],owner_id=user['id'],instance_id=metadata['instance_id']))
    client=TestClient(main.app,base_url='http://100.66.11.2:8765',headers={'Origin':'http://100.66.11.2:8765','X-ORH-Request':'1'})
    response=client.get('/auth/cloud/start',follow_redirects=False)
    assert response.status_code==307
    assert 'orh_cloud_state=' in response.headers['set-cookie']
    intent=json.loads(parse_qs(urlsplit(response.headers['location']).fragment)['authorize'][0])
    assert intent['device']==metadata['instance_id']
    assert client.post('/auth/cloud/exchange',json={'ticket':'x'*32,'state':'wrong'}).status_code==403


def test_cgnat_address_classification():
    import ipaddress
    assert cloud_agent.local_address(ipaddress.ip_address('100.66.11.2'))
    assert not cloud_agent.local_address(ipaddress.ip_address('100.128.0.1'))
    assert not cloud_agent.local_address(ipaddress.ip_address('127.0.0.1'))
    assert not cloud_agent.local_address(ipaddress.ip_address('198.18.0.1'))


def test_metadata_keeps_direct_local_entry_and_new_tailscale_address(monkeypatch):
    from app.network import Network
    from app.remote_connect import tailscale
    monkeypatch.setenv('ORH_HOST','0.0.0.0')
    monkeypatch.setenv('ORH_ALLOWED_HOSTS','192.168.1.20')
    monkeypatch.setattr(main,'NETWORK',Network.load())
    monkeypatch.setattr(main,'PORT',8765)
    monkeypatch.setattr(cloud_agent.psutil,'net_if_stats',lambda:{})
    monkeypatch.setattr(tailscale,'json_command',lambda argv:{'Self':{'TailscaleIPs':['100.66.11.2'],'DNSName':'mac.example.ts.net.'}})
    value=cloud_agent.metadata()
    assert value['addresses'][0] != 'http://127.0.0.1:8765'
    assert 'http://127.0.0.1:8765' in value['addresses']
    assert 'http://localhost:8765' in value['addresses']
    assert 'http://100.66.11.2:8765' in value['addresses']
    assert '100.66.11.2' in main.NETWORK.hosts
