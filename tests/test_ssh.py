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
    return post(client, '/config/apply', dict(plan=plan['plan'], confirm='config'))


def test_include_priority_duplicates_and_conflicts(ssh_home):
    client, directory, _ = ssh_home
    (directory / 'extra file.conf').write_text('Host external\n HostName example.org\n User remote\n')
    (directory / 'config').write_text('Include "' + str(directory / 'extra file.conf') + '"\nHost *\n User fallback\n')
    original = (directory / 'config').read_text()
    row = add(client, user='chosen')
    assert (directory / 'config').read_text() == original
    assert client.post('/api/ssh/connections/test/diagnose', json={}).status_code == 409
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
    exported = client.post('/api/ssh/keys/testkey/export', json={})
    assert exported.status_code == 200
    assert b'PRIVATE KEY' in exported.content
    assert client.post('/api/ssh/keys/testkey/export', json={}).status_code == 200
    post(client, '/keys/import', dict(name='imported', private=exported.text, public=row['public'], passphrase=passphrase))
    post(client, '/keys/testkey/passphrase', dict(old_passphrase=passphrase, passphrase='changed secret',
              revision=listing['revision']))
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
    response = client.get('/api/ssh/overview')
    assert response.status_code == 200
    assert not response.json()['files'][0]['editable']
    assert client.post('/api/ssh/config/plan', json={'action':'include'}).status_code == 403
    assert target.read_text() == 'secret'
    (directory / 'config').unlink()
    marker = tmp_path / 'must-not-execute'
    (directory / 'config').write_text(f'Host external\n HostName localhost\nMatch exec "touch {marker}"\n User root\n')
    overview = client.get('/api/ssh/overview').json()
    assert overview['has_command_rules']
    assert client.get('/api/ssh/connections/external/effective').status_code == 200
    assert marker.exists()
    public = post(client, '/keys/generate', dict(name='key'))
    os.chmod(directory / 'key', 0o644)
    response = client.post('/api/ssh/keys/key/export', json={})
    assert response.status_code == 403
    assert 'PRIVATE KEY' not in response.text


def test_admin_session_authorizes_operations_without_reauthentication(ssh_home):
    client, directory, _ = ssh_home
    post(client, '/keys/generate', dict(name='key'))
    for _ in range(2):
        response = client.post('/api/ssh/keys/key/export', json={})
        assert response.status_code == 200 and b'PRIVATE KEY' in response.content
    assert client.post('/api/ssh/reauth', json={}).status_code == 404
    remote = TestClient(main.app, base_url=f'http://127.0.0.1:{main.PORT}', client=('8.8.8.8', 50000), headers={'X-ORH-Request': '1'})
    remote.cookies.set('orh', client.cookies.get('orh'))
    assert remote.post('/api/ssh/keys/key/export', json={}).status_code == 403
    assert remote.post('/api/ssh/keys/generate', json=dict(name='unsafe')).status_code == 403
    client.post('/api/logout', json={})
    assert client.get('/api/ssh/overview').status_code == 401
    assert client.post('/api/ssh/keys/key/export', json={}).status_code == 401


def test_advanced_diff_backups_and_version_conflict(ssh_home):
    client, directory, _ = ssh_home
    (directory / 'config').write_text('Host original\n HostName 127.0.0.1\n')
    info = client.get('/api/ssh/config').json()['files'][0]
    opened = post(client, '/config/read', dict(file=info['id']))
    plan = post(client, '/config/plan', dict(file=info['id'], revision=opened['revision'], text=opened['text'] + '\nHost added\n HostName localhost\n'))
    assert '+Host added' in plan['diff']
    post(client, '/config/apply', dict(plan=plan['plan'], confirm='config'))
    assert 'Host added' in (directory / 'config').read_text()
    assert client.post('/api/ssh/config/plan', json=dict(file=info['id'], revision=opened['revision'], text='stale')).status_code == 409
    backup = store.rows('backup')[0]
    post(client, '/backups/restore', dict(backup=backup['id'], revision=store.revision('config'), confirm='config'))
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
    response = client.post('/api/ssh/keys/key/delete', json=dict(confirm='key', revision=row['revision'], public_revision=row['public_revision']))
    assert response.status_code == 409
    connection = store.rows('connection')[0]
    cfg.delete_connection('test', store.revision(cfg.MANAGED), connection['revision'])
    (directory / 'config').write_text('Host *\n IdentityFile "' + str(directory / 'key') + '"\n')
    assert keys.references('key')['rules']
    (directory / 'config').unlink()
    removed = post(client, '/keys/key/delete', dict(confirm='key', revision=row['revision'], public_revision=row['public_revision']))
    assert not (directory / 'key').exists()
    for token in removed['backups']:
        backup = store.get('backup', token)
        post(client, '/backups/restore', dict(backup=token, revision=store.revision(backup['file']), confirm=backup['file']))
    assert (directory / 'key').exists() and (directory / 'key.pub').exists()


def test_managed_backup_restore_and_crash_reconciliation(ssh_home):
    client, directory, _ = ssh_home
    first = add(client, 'first')
    second = add(client, 'second')
    backup = store.rows('backup')[-1]
    post(client, '/backups/restore', dict(backup=backup['id'], revision=store.revision(cfg.MANAGED), confirm=cfg.MANAGED))
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
    post(client, '/config/apply', dict(plan=plan['plan'], confirm='includes/complex name.conf'))
    assert not marker.exists()
    assert cfg.discover()['has_command_rules']
    assert client.get('/api/ssh/connections/fixture/effective').status_code == 200
    info = next(f for f in cfg.discover()['files'] if f['path'] == str(included))
    invalid = client.post('/api/ssh/config/plan', json=dict(file=info['id'], text='DefinitelyNotSSHOption value\n', revision=info['revision']))
    assert invalid.status_code == 400
    assert included.read_text() == text


def test_import_mismatch_and_config_cannot_export_private_material(ssh_home):
    client, directory, _ = ssh_home
    first = post(client, '/keys/generate', dict(name='one'))
    other = post(client, '/keys/generate', dict(name='two'))
    private = (directory / 'one').read_text()
    mismatch = client.post('/api/ssh/keys/import', json=dict(name='mismatch', private=private, public=other['public']))
    assert mismatch.status_code == 400
    assert not (directory / 'mismatch').exists()
    (directory / 'config').write_text('Include "' + str(directory / 'one') + '"\n')
    inventory = client.get('/api/ssh/config').json()
    assert len(inventory['files']) == 1
    assert inventory['warnings']
    assert private not in json.dumps(inventory)
    assert not list(directory.glob('.orh-key-*'))


def test_parallel_generation_never_overwrites_and_authenticated_exports_work(ssh_home):
    from concurrent.futures import ThreadPoolExecutor
    client, directory, _ = ssh_home
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda _: client.post('/api/ssh/keys/generate', json=dict(name='race')), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda _: client.post('/api/ssh/keys/race/export', json={}), range(2)))
    assert [r.status_code for r in responses] == [200, 200]


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


def test_public_http_cannot_open_owned_ssh_terminal(ssh_home):
    from starlette.websockets import WebSocketDisconnect
    client, directory, _ = ssh_home
    store.put('terminal', 'fixture', dict(host='test', session='ssh-test-guard', state='completed', signature='fixture', created=0))
    remote = TestClient(main.app, base_url=f'http://127.0.0.1:{main.PORT}', client=('8.8.8.8', 50000), headers={'X-ORH-Request':'1'})
    remote.cookies.set('orh', client.cookies.get('orh'))
    assert remote.get('/terminal/ssh-test-guard').status_code == 403
    origin = f'http://127.0.0.1:{main.PORT}'
    assert remote.post('/terminal/session?session=ssh-test-guard', headers={'Origin':origin}).status_code == 403
    with pytest.raises(WebSocketDisconnect):
        with remote.websocket_connect(origin.replace('http:', 'ws:') + '/terminal/ws/terminal/ssh-test-guard?web_client_id=fixture&rows=24&cols=80', headers={'Origin':origin}):
            pass


def test_organizing_managed_connection_keeps_revision_and_group_consistent(ssh_home):
    client, directory, _ = ssh_home
    row = add(client, group='old')
    organized = post(client, '/connections/metadata', dict(alias='test', group='favorite-group', favorite=True))
    assert organized['revision'] != row['revision']
    view = client.get('/api/ssh/overview').json()
    row = view['connections'][0]
    assert row['favorite'] and row['group'] == 'favorite-group'
    post(client, '/connections/save', dict(row, original_alias='test', connection_revision=row['revision'],
                                         managed_revision=view['managed_revision'], group='edited'))
    row = client.get('/api/ssh/overview').json()['connections'][0]
    assert row['group'] == 'edited'
    assert row['favorite']


def test_interrupted_key_pair_deletion_rolls_back(ssh_home, monkeypatch):
    client, directory, _ = ssh_home
    post(client, '/keys/generate', dict(name='rollback'))
    original = (directory / 'rollback').read_bytes()
    row = client.get('/api/ssh/keys').json()['keys'][0]
    unlink = Path.unlink
    def interrupted(path, *args, **kwargs):
        if path == directory / 'rollback.pub':
            raise PermissionError('isolated test interruption')
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', interrupted)
    response = client.post('/api/ssh/keys/rollback/delete', json=dict(confirm='rollback', revision=row['revision'], public_revision=row['public_revision']))
    assert response.status_code == 409
    assert (directory / 'rollback').read_bytes() == original
    assert (directory / 'rollback.pub').exists()


@pytest.mark.parametrize('password', ['', 'encrypted-pem-fixture'])
def test_import_and_change_rsa_pem_passphrase(ssh_home, password):
    from app.ssh.process import keygen
    client, directory, _ = ssh_home
    source = directory / 'rsa-source'
    keygen(['ssh-keygen', '-q', '-m', 'PEM', '-t', 'rsa', '-b', '2048', '-f', str(source)], [password, password])
    imported = post(client, '/keys/import', dict(name='pem-import', private=source.read_text(), passphrase=password))
    row = next(key for key in client.get('/api/ssh/keys').json()['keys'] if key['name'] == 'pem-import')
    assert row['encrypted'] == bool(password)
    post(client, '/keys/pem-import/passphrase', dict(revision=row['revision'], old_passphrase=password, passphrase='replacement-phrase'))
    derived = keygen(['ssh-keygen', '-y', '-f', str(directory / 'pem-import')], ['replacement-phrase'])
    assert keys.public_line(derived)['fingerprint'] == imported['fingerprint']


def test_keygen_secret_never_enters_argv_or_environment(ssh_home, monkeypatch):
    import subprocess
    client, directory, data = ssh_home
    secret = 'private-unicode-口令-fixture'
    original = subprocess.Popen
    calls = []
    def inspected(argv, **kwargs):
        calls.append((argv, kwargs.get('env', {})))
        return original(argv, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', inspected)
    post(client, '/keys/generate', dict(name='secret-check', passphrase=secret))
    assert calls
    for argv, environment in calls:
        assert all(secret not in str(argument) for argument in argv)
        assert secret not in json.dumps(environment)
    for path in list(directory.rglob('*')) + list(data.rglob('*')):
        if path.is_file():
            assert secret.encode() not in path.read_bytes()


def test_bounded_process_timeout_and_cancel():
    from app.ssh.process import run
    from fastapi import HTTPException
    import threading
    with pytest.raises(HTTPException) as error:
        run([sys.executable, '-c', 'import time;time.sleep(10)'], timeout=.2)
    assert error.value.status_code == 504
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(HTTPException) as error:
        run([sys.executable, '-c', 'import time;time.sleep(10)'], cancel=cancel)
    assert error.value.status_code == 409


def test_linked_include_native_rules_use_admin_login(ssh_home, tmp_path):
    client, directory, _ = ssh_home
    source = tmp_path / 'native-tool.conf'
    marker = tmp_path / 'must-not-execute-linked-rule'
    source.write_text(f'Host linked\n HostName localhost\nMatch exec "touch {marker}"\n User alternate\n')
    include = directory / 'native-tool.conf'
    include.symlink_to(source)
    (directory / 'config').write_text('Include "' + str(include) + '"\n')
    found = client.get('/api/ssh/config').json()
    assert found['has_command_rules']
    linked = next(row for row in found['files'] if row['path'] == str(include))
    assert linked['read_path'] == str(source) and not linked['editable']
    assert client.get('/api/ssh/connections/linked/effective').status_code == 200
    assert marker.exists()
    raw = post(client, '/config/read', dict(file=linked['id']))
    assert 'Match exec' in raw['text']
    before = found['signature']
    source.write_text(source.read_text() + '# edited externally\n')
    assert cfg.discover()['signature'] != before


def test_bad_config_can_be_opened_for_repair_without_executing_it(ssh_home):
    client, directory, _ = ssh_home
    (directory / 'config').write_text('Host repair\n HostName "unterminated\n')
    found = client.get('/api/ssh/config').json()
    assert found['warnings'] and found['unverified_sources']
    assert client.get('/api/ssh/connections/repair/effective').status_code == 409
    info = found['files'][0]
    post(client, '/config/read', dict(file=info['id']))
    plan = post(client, '/config/plan', dict(file=info['id'], revision=info['revision'], text='Host repair\n HostName localhost\n'))
    post(client, '/config/apply', dict(plan=plan['plan'], confirm='config'))
    assert client.get('/api/ssh/connections/repair/effective').json()['hostname'] == 'localhost'


@pytest.mark.parametrize('address', ['192.168.31.20', '10.2.3.4', '172.20.1.2', '100.66.1.3', 'fd12::3', '::ffff:192.168.31.20'])
def test_private_network_http_supports_key_and_terminal_operations(ssh_home, monkeypatch, address):
    from app import terminal_entry
    from app.ssh import terminals
    client, directory, _ = ssh_home
    remote = TestClient(main.app, base_url=f'http://127.0.0.1:{main.PORT}', client=(address, 50000),
                        headers={'X-ORH-Request':'1', 'Origin':f'http://127.0.0.1:{main.PORT}'})
    remote.cookies.set('orh', client.cookies.get('orh'))
    post(remote, '/keys/generate', dict(name='private-http-key'))
    exported = remote.post('/api/ssh/keys/private-http-key/export', json={})
    assert exported.status_code == 200 and 'PRIVATE KEY' in exported.text
    status = remote.get('/api/ssh/overview').json()
    assert status['transport_allowed'] and not status['secure_transport']
    store.put('terminal', 'private-fixture', dict(host='private', session='ssh-private-http', state='completed', signature='fixture', created=0))
    monkeypatch.setattr(terminal_entry, 'prepare', lambda name:dict(url='/terminal/' + name))
    assert remote.post('/api/zellij/ssh-private-http/enter', json={}).status_code == 200
    monkeypatch.setattr(terminals, 'launch', lambda host, new:dict(session='ssh-private-http', url='/terminal/ssh-private-http'))
    assert remote.post('/api/ssh/connections/private/connect', json={}).status_code == 200

    # Exercise the authenticated native WS gateway with a bounded upstream stub.
    # The SSH protocol and real Zellij upstream are covered by the separate live suite.
    import contextlib
    from types import SimpleNamespace
    from app import native_terminal
    class UpstreamSocket:
        async def send(self, data):
            pass
        async def __aiter__(self):
            yield 'private-http-ws-accepted'
    @contextlib.asynccontextmanager
    async def connection(url, cookie):
        yield UpstreamSocket()
    async def authenticate():
        return SimpleNamespace(cookies={})
    monkeypatch.setattr(native_terminal, 'native_connection', connection)
    monkeypatch.setattr(native_terminal, 'upstream', SimpleNamespace(authenticate=authenticate, base=lambda:'http://127.0.0.1:8082'))
    origin = f'http://127.0.0.1:{main.PORT}'
    with remote.websocket_connect(origin.replace('http:', 'ws:') + '/terminal/ws/terminal/ssh-private-http?web_client_id=fixture&rows=24&cols=80', headers={'Origin':origin}) as terminal:
        assert terminal.receive_text() == 'private-http-ws-accepted'


def test_http_network_configuration_and_forwarded_header_boundary(ssh_home, monkeypatch):
    client, directory, _ = ssh_home
    remote = TestClient(main.app, base_url=f'http://127.0.0.1:{main.PORT}', client=('8.8.8.8', 50000), headers={'X-ORH-Request':'1'})
    remote.cookies.set('orh', client.cookies.get('orh'))
    assert remote.post('/api/ssh/keys/generate', json={'name':'blocked'}, headers={'X-Forwarded-For':'192.168.31.20'}).status_code == 403
    monkeypatch.setenv('ORH_SSH_HTTP_NETWORKS', '8.8.8.8/32')
    assert remote.post('/api/ssh/keys/generate', json={'name':'custom-network'}).status_code == 200
    monkeypatch.setenv('ORH_SSH_HTTP_NETWORKS', 'invalid')
    assert remote.post('/api/ssh/keys/generate', json={'name':'invalid-policy'}).status_code == 503


@pytest.mark.parametrize('algorithm,bits,kind', [('ed25519',None,'ED25519'), ('rsa',2048,'RSA'), ('rsa',3072,'RSA'), ('rsa',4096,'RSA'), ('ecdsa',256,'ECDSA'), ('ecdsa',384,'ECDSA'), ('ecdsa',521,'ECDSA')])
def test_supported_key_generation_algorithms(ssh_home, algorithm, bits, kind):
    client, directory, _ = ssh_home
    result = post(client, '/keys/generate', dict(name='multi-algorithm', algorithm=algorithm, bits=bits, passphrase='algorithm-fixture'))
    assert result['type'] == kind
    if bits:
        assert result['bits'] == bits
    from app.ssh.process import keygen
    public = keygen(['ssh-keygen','-y','-f',str(directory/'multi-algorithm')], ['algorithm-fixture'])
    assert keys.public_line(public)['fingerprint'] == result['fingerprint']
    for algorithm, bits in [('dsa',1024), ('rsa',1024), ('rsa;id',2048), ('ecdsa',4096)]:
        assert client.post('/api/ssh/keys/generate', json=dict(name='invalid-algorithm', algorithm=algorithm, bits=bits)).status_code == 400


@pytest.mark.parametrize('authentication,preferred,pubkey', [
    ('password', 'keyboard-interactive,password', False),
    ('key', 'publickey', True),
])
def test_connection_authentication_modes_use_native_ssh_config(ssh_home, authentication, preferred, pubkey):
    from app.ssh import terminals
    client, directory, _ = ssh_home
    post(client, '/keys/generate', dict(name='identity'))
    row = add(client, authentication=authentication, identityfile=str(directory / 'identity'))
    link(client)
    effective = client.get('/api/ssh/connections/test/effective').json()
    assert effective['preferredauthentications'] == preferred
    assert (effective['pubkeyauthentication'] in ('yes', 'true')) == pubkey
    assert row['authentication'] == authentication
    # Explicit deployment verification can still use a key on a password-mode connection.
    command = terminals.argv('test', identity='identity')
    assert 'PubkeyAuthentication=yes' in command
    invalid = client.post('/api/ssh/connections/save', json=dict(alias='invalid', authentication='password;id'))
    assert invalid.status_code == 400
