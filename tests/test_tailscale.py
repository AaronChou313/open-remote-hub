import json
from pathlib import Path
import subprocess
import sys

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.remote_connect import tailscale


@pytest.fixture
def tail(monkeypatch):
    prefs={'accept-dns':True,'accept-routes':True,'shields-up':False,'exit-node':'','exit-node-allow-lan-access':False}
    state={'Version':'1.104.7','BackendState':'Running','AuthURL':'','Health':[],
           'CurrentTailnet':{'Name':'private-account','MagicDNSSuffix':'example.ts.net','MagicDNSEnabled':True},
           'Self':{'ID':'self','HostName':'mac','DNSName':'mac.example.ts.net.','TailscaleIPs':['100.66.11.2'],'Online':True,'PublicKey':'private-key-material'},
           'Peer':{'secret-public-map-key':{'ID':'peer-one','HostName':'Windows','DNSName':'windows.example.ts.net.','TailscaleIPs':['100.66.11.3'],'Online':True,'Active':True,'CurAddr':'192.168.1.10:41641','Relay':'sin','ExitNodeOption':True}}}
    calls=[]
    def command(argv,timeout=10):
        calls.append(argv)
        if argv==['status','--json']:return json.dumps(state)
        if argv==['get','--json']:return json.dumps(prefs)
        if argv[0]=='set':
            for flag in argv[1:]:
                name,value=flag[2:].split('=',1)
                prefs[name]= {'true':True,'false':False}.get(value,value)
            return ''
        if argv[0]=='ping':return 'pong from Windows via 192.168.1.10:41641 in 2ms'
        if argv[0]=='netcheck':return 'Report:\nUDP: true\nSingapore: 2ms'
        return ''
    monkeypatch.setattr(tailscale,'binary',lambda:'/native/tailscale')
    monkeypatch.setattr(tailscale,'command',command)
    monkeypatch.setattr(tailscale,'operation',None)
    return prefs,state,calls


def test_status_sanitized_native_routes(tail):
    result=tailscale.status()
    assert result['state']=='Running'
    assert result['device']['dns']=='mac.example.ts.net'
    assert result['peers'][0]['route']=='direct'
    assert result['network']=='example.ts.net'
    assert 'private-key-material' not in json.dumps(result)
    assert 'secret-public-map-key' not in json.dumps(result)
    assert 'private-account' not in json.dumps(result)
    tail[1]['Peer']['secret-public-map-key']['CurAddr']=''
    assert tailscale.status()['peers'][0]['route']=='relay'
    tail[1]['Peer']['secret-public-map-key']['Active']=False
    assert tailscale.status()['peers'][0]['route']=='idle'


def test_settings_only_changed_flags_and_conflicts(tail):
    prefs,_,calls=tail
    before=dict(prefs)
    tailscale.save_preferences({'accept-dns':False},before)
    assert ['set','--accept-dns=false'] in calls
    assert prefs['accept-routes'] is True
    with pytest.raises(ValueError):tailscale.save_preferences({'accept-dns':True},before)
    before=dict(prefs)
    with pytest.raises(ValueError):tailscale.save_preferences({'shields-up':True},before)
    tailscale.save_preferences({'shields-up':True},before,True)
    assert ['set','--shields-up=true'] in calls
    tailscale.save_preferences({'exit-node':'100.66.11.3'},dict(prefs),True)
    assert ['set','--exit-node=100.66.11.3'] in calls


@pytest.mark.parametrize('changes',[
    {'arbitrary-command':'logout'},{'accept-dns':'true'},{'exit-node':'--reset'}, {'exit-node':'1.2.3.4; id'},
])
def test_preferences_reject_unbounded_input(tail,changes):
    with pytest.raises(ValueError):tailscale.save_preferences(changes,dict(tail[0]),True)
    assert not any(call[0]=='set' for call in tail[2])


def test_known_peer_ping_netcheck(tail):
    assert 'pong' in tailscale.ping('peer-one')['output']
    assert tail[2][-1]==['ping','--c=3','--timeout=3s','--until-direct=true','100.66.11.3']
    with pytest.raises(ValueError):tailscale.ping('--reset')
    result=tailscale.netcheck()
    assert 'UDP: true' in result['output'] and 'Singapore' in result['output']


def test_control_confirmation_and_background_result(tail):
    with pytest.raises(ValueError):tailscale.control('disconnect')
    result=tailscale.control('reconnect',True)
    assert result['state']=='pending'
    with pytest.raises(ValueError):tailscale.control('connect')
    tailscale.run_operation('reconnect')
    assert tail[2][-2:]==[['down','--accept-risk=lose-ssh'],['up']]
    assert tailscale.status()['last_operation']['state']=='done'


def test_timeout_and_unavailable(monkeypatch):
    monkeypatch.setattr(tailscale,'binary',lambda:None)
    assert tailscale.status()['available'] is False
    monkeypatch.setattr(tailscale,'binary',lambda:'/native/tailscale')
    def run(*args,**kwargs):raise tailscale.TailscaleError('ORN 请求超时')
    monkeypatch.setattr(tailscale,'request',run)
    with pytest.raises(tailscale.TailscaleError):tailscale.command(['status','--json'])
    result=tailscale.status()
    assert result['reachable'] is False and '超时' in result['error']
