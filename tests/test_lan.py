"""LAN inventory must distinguish cache entries from confirmed reachability."""
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.remote_connect import lan
from test_files import workspace


@pytest.fixture
def local_network(monkeypatch, workspace):
    monkeypatch.setattr(lan, 'checks', {})
    links = [dict(name='en0', ip='192.168.7.2', network='192.168.7.0/24', mac='aa:bb:cc:00:00:01'),
             dict(name='en1', ip='192.168.7.3', network='192.168.7.0/24', mac='aa:bb:cc:00:00:02')]
    monkeypatch.setattr(lan, 'interfaces', lambda:links)
    monkeypatch.setattr(lan.platforms, 'lan_details', lambda:dict(gateways=[dict(address='192.168.7.1',interface='en0')],dns=['192.168.7.1']))
    monkeypatch.setattr(lan.platforms, 'lan_neighbors', lambda:[dict(ip='192.168.7.10',mac='aa:bb:cc:00:00:10',interface='en0'),dict(ip='192.168.7.255',mac='ff:ff:ff:ff:ff:ff',interface='en0'),dict(ip='192.168.7.10',mac='aa:bb:cc:99:99:99',interface='bridge100')])
    return workspace[0]


def test_inventory_deduplicates_host_and_does_not_assume_online(local_network):
    rows = lan.status()['devices']
    assert len(rows) == 2
    own = next(row for row in rows if row['state']=='self')
    assert own['addresses']==['192.168.7.2','192.168.7.3']
    assert len(own['macs'])==2
    assert next(row for row in rows if row['state']!='self')['state']=='known'


def test_discovery_stays_in_local_subnet_and_persists_notes(local_network, monkeypatch):
    addresses=[]
    def ping(address):
        addresses.append(address)
        return address=='192.168.7.10'
    monkeypatch.setattr(lan.platforms,'lan_ping',ping)
    result=lan.scan()
    assert len(addresses)==254 and all(address.startswith('192.168.7.') for address in addresses)
    device=next(row for row in result['devices'] if row['state']=='online')
    lan.save_note(device['id'],'NAS <test>')
    assert next(row for row in lan.status()['devices'] if row['id']==device['id'])['note']=='NAS <test>'
    with pytest.raises(ValueError):lan.save_note('unknown','name')


def test_lan_api_uses_console_auth(local_network):
    assert local_network.get('/api/remote-connect/lan').status_code==200
    local_network.cookies.clear()
    assert local_network.get('/api/remote-connect/lan').status_code==401
