"""The public portal can identify a host without opening management APIs."""
import stat
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient
from app import main, discovery, passwords
from app.network import Network

ORIGIN = 'https://aaronchou313.github.io'


def configure(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DATA', tmp_path)
    monkeypatch.setattr(main, 'NETWORK', Network('0.0.0.0', frozenset(['127.0.0.1', 'mac.local'])))
    monkeypatch.setenv('ORH_DISCOVERY_ORIGINS', ORIGIN)
    monkeypatch.setenv('ORH_INSTANCE_NAME', 'Mac mini')
    return TestClient(main.app, base_url=f'http://mac.local:{main.PORT}')


def test_public_identity_and_narrow_cors(tmp_path, monkeypatch):
    client = configure(tmp_path, monkeypatch)
    response = client.get(discovery.PATH, headers={'Origin':ORIGIN})
    assert response.status_code == 200
    value = response.json()
    assert set(value) == {'service', 'protocol', 'instance_id', 'name'}
    assert value['name'] == 'Mac mini'
    assert response.headers['access-control-allow-origin'] == ORIGIN
    assert 'access-control-allow-credentials' not in response.headers
    assert client.get(discovery.PATH).json()['instance_id'] == value['instance_id']
    assert stat.S_IMODE((tmp_path / 'instance-id').stat().st_mode) == 0o600
    assert client.options(discovery.PATH, headers={'Origin':ORIGIN}).status_code == 204
    assert client.get(discovery.PATH, headers={'Origin':'https://evil.example'}).status_code == 403
    assert client.get(discovery.PATH, headers={'Host':'evil.example:8765','Origin':ORIGIN}).status_code == 400
    assert client.get('/api/me', headers={'Origin':ORIGIN}).status_code == 403
    assert client.get('/api/me').status_code == 401
    assert client.get('/api/discovery').status_code == 401
    assert client.post('/api/login', json={'password':'x'}, headers={'Origin':ORIGIN,'X-ORH-Request':'1'}).status_code == 403


def test_authenticated_pairing_and_instance_stability(tmp_path, monkeypatch):
    from urllib.parse import urlsplit, parse_qs
    import json
    client = configure(tmp_path, monkeypatch)
    passwords.save('test', initial=True)
    assert client.post('/api/login', json={'password':'test'}, headers={'X-ORH-Request':'1'}).status_code == 200
    result = client.get('/api/discovery').json()
    assert 'http://mac.local:8765' in result['urls']
    assert 'http://127.0.0.1:8765' not in result['urls']
    payload = json.loads(parse_qs(urlsplit(result['portal_url']).fragment)['add'][0])
    assert payload['instanceId'] == discovery.identity()['instance_id']
    assert payload['urls'] == result['urls']
    assert urlsplit(result['portal_url']).query == ''
    assert 'password' not in result and 'token' not in result
