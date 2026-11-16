"""Cloud-independent recovery and explicitly configured private-network access."""
import json
import time

import pytest
from fastapi import HTTPException

from app import access, agent_settings, cloud_agent, main, passwords, client
from app.network import Network
from app.remote_connect import tailscale
from test_files import workspace


@pytest.fixture
def bound_agent(workspace, monkeypatch):
    http=workspace[0]
    monkeypatch.setattr(main,'NETWORK',Network.configured('127.0.0.1',[]))
    cloud_agent.save(dict(status='bound',cloud_url='https://cloud.invalid',owner_id='owner',credential='device-secret'))
    access.create('cloud-session','admin',time.time()+600)
    http.cookies.clear();http.cookies.set('orh','cloud-session',domain='127.0.0.1')
    monkeypatch.setattr(cloud_agent,'call',lambda *args,**kwargs:pytest.fail('Local recovery cannot contact Cloud'))
    return http


def test_bound_recovery_is_opt_in_and_password_rotation_keeps_cloud_session(bound_agent):
    http=bound_agent
    assert http.post('/api/login',json={'password':'files-test-password'}).status_code==409
    settings=dict(bind='0.0.0.0',allowed_hosts=['10.77.1.2'],recovery_enabled=True,password='recovery-fixture-123')
    response=http.post('/api/agent/settings',json=settings)
    assert response.status_code==200,response.text
    assert response.json()['restart_required']
    assert 'recovery-fixture-123' not in response.text+passwords.path().read_text()
    assert main.NETWORK.bind=='127.0.0.1'
    assert agent_settings.configured_network(main.NETWORK).bind=='0.0.0.0'
    assert main.NETWORK.allows('10.77.1.2:'+str(main.PORT),main.PORT)
    assert not main.NETWORK.allows('evil.invalid:'+str(main.PORT),main.PORT)
    assert http.get('/api/me').status_code==200
    assert http.post('/api/login',json={'password':'wrong-password'}).status_code==401
    assert http.post('/api/login',json={'password':settings['password']}).status_code==200
    recovery=http.cookies.get('orh')
    assert access.get(recovery)
    http.cookies.clear();http.cookies.set('orh','cloud-session',domain='127.0.0.1')
    assert http.post('/api/agent/settings',json={**settings,'password':'new-recovery-fixture'}).status_code==200
    assert access.get(recovery) is None
    assert access.get('cloud-session')
    assert http.post('/api/agent/settings',json={**settings,'recovery_enabled':False,'password':''}).status_code==200
    assert http.post('/api/login',json={'password':'new-recovery-fixture'}).status_code==409


def test_settings_validate_destinations_and_require_a_new_recovery_secret(bound_agent):
    body=dict(bind='0.0.0.0',allowed_hosts=['*'],recovery_enabled=False)
    assert bound_agent.post('/api/agent/settings',json=body).status_code==400
    body['allowed_hosts']=['100.100.1.2'];body['recovery_enabled']=True
    assert bound_agent.post('/api/agent/settings',json=body).status_code==400
    assert not agent_settings.recovery_enabled()
    assert not agent_settings.path().exists()


def test_agent_management_api_survives_mesh_failure(bound_agent,monkeypatch):
    monkeypatch.setattr(tailscale,'request',lambda *args,**kwargs:(_ for _ in ()).throw(tailscale.TailscaleError('Mesh offline')))
    assert bound_agent.get('/api/me').status_code==200
    assert bound_agent.get('/api/system').status_code==200
    status=bound_agent.get('/api/client/mesh')
    assert status.status_code==200 and status.json()['error']=='Mesh offline'


def test_cached_directory_opens_identity_checked_gateway_for_recovery(bound_agent,monkeypatch):
    local=client.discovery.identity()['instance_id']
    device=dict(instance_id='remote-id',name='Remote',os='Linux',mesh={'ips':['100.64.0.9'],'services':[8765]})
    monkeypatch.setattr(cloud_agent,'directory',lambda strict=False:[device])
    monkeypatch.setattr(tailscale,'status',lambda:dict(state='Running',peers=[dict(addresses=['100.64.0.9'],route='direct')]))
    assert bound_agent.get('/api/client/devices').json()['devices'][1 if local=='remote-id' else 0] is not None
    def offline(strict=False):raise HTTPException(503,'Cloud offline')
    monkeypatch.setattr(cloud_agent,'directory',offline)
    calls=[]
    monkeypatch.setattr(tailscale,'request',lambda path,body=None,**kwargs:calls.append((path,body)) or {'url':'http://orh-target.localhost:12345/auth/cloud/enter'})
    response=bound_agent.post('/api/client/connect',json={'device_id':'remote-id'})
    assert response.status_code==200,response.text
    assert '/auth/cloud/enter' not in response.json()['url']
    assert calls==[('/console',{'peer_ip':'100.64.0.9','device_id':'remote-id'})]
    assert json.loads((main.DATA/'device-directory.json').read_text())['account']==cloud_agent.fingerprint()
    monkeypatch.setattr(cloud_agent,'fingerprint',lambda:'another-account')
    assert client.account_directory()[0]==[]


def test_generic_tcp_forward_reuses_mesh_api(workspace,monkeypatch):
    http=workspace[0];calls=[]
    monkeypatch.setattr(tailscale,'request',lambda path,body=None,**kwargs:calls.append((path,body,kwargs)) or {'ok':True})
    assert http.post('/api/client/mesh/forward',json={'peer_ip':'100.64.0.9','remote_port':22,'local_port':10022}).status_code==200
    assert calls[-1][1]=={'peer_ip':'100.64.0.9','remote_port':22,'local_port':10022}
    assert http.post('/api/client/mesh/forward',json={'peer_ip':'100.64.0.9','remote_port':0}).status_code==400
    key='a'*24
    assert http.post('/api/client/mesh/close',json={'id':key}).status_code==200
    assert calls[-1]==('/forwards/'+key,None,{'method':'DELETE'})
