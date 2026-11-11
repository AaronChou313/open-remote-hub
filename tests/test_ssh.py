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


def test_hashed_known_hosts_scoped_removal_and_shared_records(ssh_home):
    from app.ssh import hosts
    from app.ssh.process import run
    client, directory, _ = ssh_home
    public = post(client, '/keys/generate', dict(name='hostkey'))['public']
    add(client, 'target')
    link(client)
    original = '127.0.0.1,other-host ' + public + '\nuntouched-host ' + public + '\n'
    (directory / 'known_hosts').write_text(original)
    state = hosts.known('target')
    assert len(state['entries']) == 1
    hosts.remove('target', state['revision'])
    remaining = (directory / 'known_hosts').read_text()
    assert 'other-host ' in remaining and 'untouched-host ' in remaining
    assert '127.0.0.1' not in remaining
    (directory / 'known_hosts').write_text('127.0.0.1 ' + public + '\n')
    run(['ssh-keygen', '-H', '-f', str(directory / 'known_hosts')])
    assert (directory / 'known_hosts').read_text().startswith('|1|')
    state = hosts.known('target')
    assert state['entries']
    hosts.remove('target', state['revision'])
    assert not (directory / 'known_hosts').read_text()


def test_key_reference_delete_restore_and_recover_public(ssh_home):
    client, directory, _ = ssh_home
    post(client, '/keys/generate', dict(name='key', passphrase='a secret'))
    original_public = (directory / 'key.pub').read_text()
    (directory / 'key.pub').unlink()
    listing = client.get('/api/ssh/keys').json()['keys'][0]
    assert listing['fingerprint'].startswith('SHA256:')
    post(client, '/keys/key/recover-public', dict(passphrase='a secret'))
    assert (directory / 'key.pub').read_text().split()[:2] == original_public.split()[:2]
    add(client, identityfile=str(directory / 'key'))
    row = client.get('/api/ssh/keys').json()['keys'][0]
    # A managed connection protects its key even before the Include is installed.
    response = client.post('/api/ssh/keys/key/delete', json=dict(confirm='key', revision=row['revision'], public_revision=row['public_revision'], grant=grant(client, 'key-delete', 'key')))
    assert response.status_code == 409
    connection = store.rows('connection')[0]
    cfg.delete_connection('test', store.revision(cfg.MANAGED), connection['revision'])
    removed = post(client, '/keys/key/delete', dict(confirm='key', revision=row['revision'], public_revision=row['public_revision'], grant=grant(client, 'key-delete', 'key')))
    assert not (directory / 'key').exists()
    for token in removed['backups']:
        backup = store.get('backup', token)
        post(client, '/backups/restore', dict(backup=token, revision=store.revision(backup['file']), confirm=backup['file'], grant=grant(client, 'backup-restore', backup['file'])))
    assert (directory / 'key').exists() and (directory / 'key.pub').exists()


def test_managed_backup_restore_and_crash_reconciliation(ssh_home):
    client, directory, _ = ssh_home
    first = add(client, 'first')
    second = add(client, 'second')
    backup = store.rows('backup')[-1]
    post(client, '/backups/restore', dict(backup=backup['id'], revision=store.revision(cfg.MANAGED), confirm=cfg.MANAGED,
             grant=grant(client, 'backup-restore', cfg.MANAGED)))
    assert [r['alias'] for r in store.rows('connection')] == ['first']
    before = store.revision(cfg.MANAGED)
    entries = [dict(alias='recovered', hostname='localhost', revision='fixture')]
    content = cfg.render(entries)
    store.put('transaction', 'connections', dict(before=before, after=store.digest(content), entries=entries))
    with store.locked():
        store.write(cfg.MANAGED, content, before)
    cfg.inventory()
    assert [r['alias'] for r in store.rows('connection')] == ['recovered']
    assert not store.get('transaction', 'connections')


def test_invalid_config_no_exec_and_nested_complex_paths(ssh_home, tmp_path):
    client, directory, _ = ssh_home
    nested = directory / 'includes'
    nested.mkdir()
    included = nested / 'complex name.conf'
    included.write_text('Host fixture\n HostName localhost\n')
    (directory / 'config').write_text('Include "' + str(included) + '"\nHost *\n User fallback\n')
    info = next(f for f in cfg.discover()['files'] if f['path'] == str(included))
    assert info['editable']
    read = post(client, '/config/read', dict(file=info['id']))
    marker = tmp_path / 'exec-must-not-run'
    text = read['text'] + f'\nMatch exec "touch {marker}"\n User alternate\n'
    plan = post(client, '/config/plan', dict(file=info['id'], text=text, revision=info['revision']))
    post(client, '/config/apply', dict(plan=plan['plan'], confirm='includes/complex name.conf', grant=grant(client, 'config-apply', 'includes/complex name.conf')))
    assert not marker.exists()
    assert cfg.discover()['requires_trust']
    assert client.get('/api/ssh/connections/fixture/effective').status_code == 409
    info = next(f for f in cfg.discover()['files'] if f['path'] == str(included))
    invalid = client.post('/api/ssh/config/plan', json=dict(file=info['id'], text='DefinitelyNotSSHOption value\n', revision=info['revision']))
    assert invalid.status_code == 400
    assert included.read_text() == text


def test_import_mismatch_and_config_cannot_export_private_material(ssh_home):
    client, directory, _ = ssh_home
    first = post(client, '/keys/generate', dict(name='one'))
    other = post(client, '/keys/generate', dict(name='two'))
    private = (directory / 'one').read_text()
    mismatch = client.post('/api/ssh/keys/import', json=dict(name='mismatch', private=private, public=other['public'], grant=grant(client, 'key-import', 'mismatch')))
    assert mismatch.status_code == 400
    assert not (directory / 'mismatch').exists()
    (directory / 'config').write_text('Include "' + str(directory / 'one') + '"\n')
    inventory = client.get('/api/ssh/config').json()
    assert len(inventory['files']) == 1
    assert inventory['warnings']
    assert private not in json.dumps(inventory)
    assert not list(directory.glob('.orh-key-*'))


def test_parallel_generation_never_overwrites_and_grants_are_single_use(ssh_home):
    from concurrent.futures import ThreadPoolExecutor
    client, directory, _ = ssh_home
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda _: client.post('/api/ssh/keys/generate', json=dict(name='race')), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    token = grant(client, 'key-export', 'race')
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda _: client.post('/api/ssh/keys/race/export', json=dict(grant=token)), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 403]


def test_config_include_loop_duplicate_hosts_and_host_match_precedence(ssh_home):
    client, directory, _ = ssh_home
    included = directory / 'included.conf'
    included.write_text('Include "' + str(directory / 'config') + '"\nHost duplicate\n HostName second.example\n')
    (directory / 'config').write_text('Host duplicate\n HostName first.example\nInclude "' + str(included) + '"\nHost *\n User fallback\n')
    found = cfg.discover()
    assert len(found['files']) == 2
    assert len(found['hosts'][0]['sources']) == 2
    # OpenSSH rejects an actual include cycle within its own recursion limit.
    assert client.get('/api/ssh/connections/duplicate/effective').status_code == 400
    included.write_text('Host duplicate\n HostName second.example\nMatch originalhost duplicate\n User matched\n')
    effective = client.get('/api/ssh/connections/duplicate/effective').json()
    assert effective['hostname'] == 'first.example'
    assert effective['user'] == 'matched'


def test_origin_csrf_readonly_and_oversized_requests(ssh_home):
    from app import access
    import secrets, time
    client, directory, _ = ssh_home
    assert client.post('/api/ssh/keys/generate', json={'name':'denied'}, headers={'Origin':'https://evil.example'}).status_code == 403
    assert client.post('/api/ssh/keys/generate', json={'name':'denied'}, headers={'X-ORH-Request':''}).status_code == 403
    response = client.post('/api/ssh/keys/generate', content=b'x' * (256 * 1024 + 1))
    assert response.status_code == 413
    token = secrets.token_urlsafe(32)
    access.create(token, 'readonly', time.time() + 30)
    client.cookies.clear()
    client.cookies.set('orh', token)
    assert client.get('/api/ssh/keys').status_code == 403


def test_real_https_console_and_dsh_listener(ssh_home):
    import ssl, subprocess, socket, time
    import httpx
    client, directory, data = ssh_home
    certificate, private = data / 'tls.crt', data / 'tls.key'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1',
                    '-keyout', str(private), '-out', str(certificate)], capture_output=True, check=True)
    private.chmod(0o600)
    with socket.socket() as one, socket.socket() as two:
        one.bind(('127.0.0.1', 0)); two.bind(('127.0.0.1', 0))
        port, dsh_port = one.getsockname()[1], two.getsockname()[1]
    code = "from pathlib import Path;from app import main;import sys,runpy;main.DATA=Path(sys.argv[1]);main.DB=main.DATA/'metrics.sqlite3';runpy.run_path('scripts/server.py',run_name='__main__')"
    env = dict(os.environ, ORH_HOST='127.0.0.1', ORH_PORT=str(port), ORH_DSH_ENABLED='1', ORH_DSH_GATEWAY_PORT=str(dsh_port),
               ORH_TLS_CERT_FILE=str(certificate), ORH_TLS_KEY_FILE=str(private))
    with (data / 'tls-server.log').open('wb') as log:
        process = subprocess.Popen([sys.executable, '-c', code, str(data)], cwd=main.ROOT, env=env, stdout=log, stderr=log)
    try:
        context = ssl.create_default_context(cafile=str(certificate))
        with httpx.Client(base_url=f'https://localhost:{port}', verify=context, trust_env=False, headers={'X-ORH-Request':'1'}) as live:
            for _ in range(60):
                try:
                    if live.get('/').status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(.1)
            else:
                raise AssertionError('Native TLS listener failed to start')
            assert live.post('/api/login', json={'password':PASSWORD}).status_code == 200
            assert all(cookie.secure for cookie in live.cookies.jar)
            assert live.get('/api/ssh/overview').json()['secure_transport']
            # The independent DSH listener shares native TLS and remains authenticated.
            response = live.get(f'https://localhost:{dsh_port}/')
            assert response.status_code in (401, 503)
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_wildcard_fingerprint_removal_excludes_only_target(ssh_home):
    from app.ssh import hosts
    client, directory, _ = ssh_home
    public = post(client, '/keys/generate', dict(name='wildcard'))['public']
    content = ('*.example.test ' + public + '\n').encode()
    entries = hosts.matching('one.example.test', content)
    remaining = hosts.remove_lines(content, entries, 'one.example.test')
    assert not hosts.matching('one.example.test', remaining)
    assert hosts.matching('two.example.test', remaining)


def test_remote_http_cannot_open_owned_ssh_terminal(ssh_home):
    from starlette.websockets import WebSocketDisconnect
    client, directory, _ = ssh_home
    store.put('terminal', 'fixture', dict(host='test', session='ssh-test-guard', state='completed', signature='fixture', created=0))
    remote = TestClient(main.app, base_url=f'http://127.0.0.1:{main.PORT}', client=('192.168.1.10', 50000), headers={'X-ORH-Request':'1'})
    remote.cookies.set('orh', client.cookies.get('orh'))
    assert remote.get('/terminal/ssh-test-guard').status_code == 403
    origin = f'http://127.0.0.1:{main.PORT}'
    assert remote.post('/terminal/session?session=ssh-test-guard', headers={'Origin':origin}).status_code == 403
    with pytest.raises(WebSocketDisconnect):
        with remote.websocket_connect(origin.replace('http:', 'ws:') + '/terminal/ws/terminal/ssh-test-guard?web_client_id=fixture&rows=24&cols=80', headers={'Origin':origin}):
            pass
