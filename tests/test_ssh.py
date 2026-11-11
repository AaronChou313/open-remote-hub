"""All SSH tests use isolated homes. Never mutate the operator's real SSH files."""
import json
import os
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import main, passwords
from app.ssh import configuration as cfg, storage as store, keys

PASSWORD = 'ssh-test-administrator'


@pytest.fixture
def ssh_home(tmp_path, monkeypatch):
    directory = tmp_path / 'ssh home'
    directory.mkdir(mode=0o700)
    data = tmp_path / 'runtime'
    data.mkdir(mode=0o700)
    monkeypatch.setattr(main, 'DATA', data)
    monkeypatch.setenv('ORH_SSH_DIR', str(directory))
    passwords.save(PASSWORD, initial=True)
    main.attempts.clear()
    client = TestClient(main.app, base_url=f'https://127.0.0.1:{main.PORT}',
                        client=('127.0.0.1', 50000), headers={'X-ORH-Request': '1'})
    assert client.post('/api/login', json={'password': PASSWORD}).status_code == 200
    return client, directory, data


def grant(client, operation, target):
    response = client.post('/api/ssh/reauth', json=dict(operation=operation, target=target, password=PASSWORD))
    assert response.status_code == 200, response.text
    return response.json()['grant']


def post(client, path, body):
    response = client.post('/api/ssh' + path, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def add(client, alias='test', **fields):
    overview = client.get('/api/ssh/overview').json()
    return post(client, '/connections/save', dict(alias=alias, hostname='127.0.0.1',
                managed_revision=overview['managed_revision'], **fields))


def link(client):
    plan = post(client, '/config/plan', {'action': 'include'})
    return post(client, '/config/apply', dict(plan=plan['plan'], confirm='config',
                grant=grant(client, 'config-apply', 'config')))


def test_include_priority_duplicates_and_conflicts(ssh_home):
    client, directory, _ = ssh_home
    (directory / 'extra file.conf').write_text('Host external\n HostName example.org\n User remote\n')
    (directory / 'config').write_text('Include "' + str(directory / 'extra file.conf') + '"\nHost *\n User fallback\n')
    original = (directory / 'config').read_text()
    row = add(client, user='chosen')
    assert (directory / 'config').read_text() == original
    link(client)
    effective = client.get('/api/ssh/connections/test/effective').json()
    assert effective['user'] == 'chosen'
    assert client.get('/api/ssh/connections/external/effective').json()['hostname'] == 'example.org'
    overview = client.get('/api/ssh/overview').json()
    assert overview['linked']
    assert any(r['alias'] == 'external' for r in overview['connections'])
    assert client.post('/api/ssh/connections/save', json=dict(alias='external', managed_revision=overview['managed_revision'])).status_code == 409
    assert client.post('/api/ssh/connections/save', json=dict(alias='test', original_alias='test', connection_revision='stale', managed_revision=overview['managed_revision'])).status_code == 409
    assert len(list((main.DATA / 'ssh-backups').iterdir())) == 1
    assert cfg.include_plan()['diff'] == ''
    assert client.post('/api/ssh/connections/delete', json=dict(alias='test', confirm='test', connection_revision=row['revision'], managed_revision='stale')).status_code == 409
    post(client, '/connections/delete', dict(alias='test', confirm='test', connection_revision=row['revision'], managed_revision=overview['managed_revision']))
    assert 'Host test' not in (directory / cfg.MANAGED).read_text()


@pytest.mark.parametrize('passphrase', ['', '中文 encrypted secret'])
def test_generate_import_export_and_passphrase(ssh_home, passphrase):
    client, directory, data = ssh_home
    row = post(client, '/keys/generate', dict(name='testkey', comment='test fixture', passphrase=passphrase))
    assert row['fingerprint'].startswith('SHA256:')
    assert (directory / 'testkey').stat().st_mode & 0o777 == 0o600
    listing = client.get('/api/ssh/keys').json()['keys'][0]
    assert listing['encrypted'] == bool(passphrase)
    exported = client.post('/api/ssh/keys/testkey/export', json=dict(grant=grant(client, 'key-export', 'testkey')))
    assert exported.status_code == 200
    assert b'PRIVATE KEY' in exported.content
    assert client.post('/api/ssh/keys/testkey/export', json={}).status_code == 403
    post(client, '/keys/import', dict(name='imported', private=exported.text, public=row['public'], passphrase=passphrase,
                                    grant=grant(client, 'key-import', 'imported')))
    post(client, '/keys/testkey/passphrase', dict(old_passphrase=passphrase, passphrase='changed secret',
              revision=listing['revision'], grant=grant(client, 'key-passphrase', 'testkey')))
    assert keys.encrypted((directory / 'testkey').read_bytes())
    assert client.post('/api/ssh/keys/generate', json=dict(name='testkey')).status_code == 409
    for file in data.rglob('*'):
        if file.is_file() and passphrase:
            assert passphrase.encode() not in file.read_bytes()
    assert 'PRIVATE KEY' not in client.get('/api/ssh/keys').text
    assert not list(directory.glob('.orh-key-*'))


def test_path_input_permissions_and_dynamic_rules(ssh_home, tmp_path):
    client, directory, _ = ssh_home
    for name in ('../escape', '/tmp/escape', '-oProxyCommand=evil', 'x\nHost *', 'config', 'test.pub'):
        assert client.post('/api/ssh/keys/generate', json=dict(name=name)).status_code in (400, 403)
    for host in ('-oProxyCommand=id', 'host;touch /tmp/evil', 'host\nUser root'):
        assert client.post('/api/ssh/connections/save', json=dict(alias=host)).status_code == 400
    target = tmp_path / 'elsewhere'
    target.write_text('secret')
    (directory / 'config').symlink_to(target)
    assert client.get('/api/ssh/overview').status_code == 403
    (directory / 'config').unlink()
    marker = tmp_path / 'must-not-execute'
    (directory / 'config').write_text(f'Host external\n HostName localhost\nMatch exec "touch {marker}"\n User root\n')
    overview = client.get('/api/ssh/overview').json()
    assert overview['requires_trust']
    assert client.get('/api/ssh/connections/external/effective').status_code == 409
    assert not marker.exists()
    public = post(client, '/keys/generate', dict(name='key'))
    os.chmod(directory / 'key', 0o644)
    response = client.post('/api/ssh/keys/key/export', json=dict(grant=grant(client, 'key-export', 'key')))
    assert response.status_code == 403
    assert 'PRIVATE KEY' not in response.text


def test_auth_secure_transport_and_reauth_binding(ssh_home):
    client, directory, _ = ssh_home
    post(client, '/keys/generate', dict(name='key'))
    token = grant(client, 'key-export', 'key')
    assert client.post('/api/ssh/keys/key/delete', json=dict(grant=token, confirm='key')).status_code == 403
    token = grant(client, 'key-export', 'key')
    assert client.post('/api/ssh/keys/key/export', json=dict(grant=token)).status_code == 200
    assert client.post('/api/ssh/keys/key/export', json=dict(grant=token)).status_code == 403
    remote = TestClient(main.app, base_url=f'http://127.0.0.1:{main.PORT}', client=('192.168.1.10', 50000), headers={'X-ORH-Request': '1'})
    remote.cookies.set('orh', client.cookies.get('orh'))
    assert remote.post('/api/ssh/reauth', json=dict(operation='key-export', target='key', password=PASSWORD)).status_code == 403
    assert remote.post('/api/ssh/keys/generate', json=dict(name='unsafe')).status_code == 403
    client.post('/api/logout', json={})
    assert client.get('/api/ssh/overview').status_code == 401


def test_advanced_diff_backups_and_version_conflict(ssh_home):
    client, directory, _ = ssh_home
    (directory / 'config').write_text('Host original\n HostName 127.0.0.1\n')
    info = client.get('/api/ssh/config').json()['files'][0]
    opened = post(client, '/config/read', dict(file=info['id'], grant=grant(client, 'config-read', info['id'])))
    plan = post(client, '/config/plan', dict(file=info['id'], revision=opened['revision'], text=opened['text'] + '\nHost added\n HostName localhost\n'))
    assert '+Host added' in plan['diff']
    post(client, '/config/apply', dict(plan=plan['plan'], confirm='config', grant=grant(client, 'config-apply', 'config')))
    assert 'Host added' in (directory / 'config').read_text()
    assert client.post('/api/ssh/config/plan', json=dict(file=info['id'], revision=opened['revision'], text='stale')).status_code == 409
    backup = store.rows('backup')[0]
    post(client, '/backups/restore', dict(backup=backup['id'], revision=store.revision('config'), confirm='config',
                grant=grant(client, 'backup-restore', 'config')))
    assert (directory / 'config').read_text() == opened['text']
