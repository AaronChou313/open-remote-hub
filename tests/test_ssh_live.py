"""Opt-in Docker OpenSSH + native Zellij integration, isolated from user SSH data."""
import contextlib
import json
import os
from pathlib import Path
import pty
import secrets
import select
import signal
import subprocess
import sys
import time

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.test_ssh import ssh_home, add, link, post, grant
from app import main, native_terminal
from app.ssh import hosts, jobs, keys, storage as store, terminals

REAL_DATA = main.DATA


def docker(*args, input_data=None):
    return subprocess.run(['docker', *args], input=input_data, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True, timeout=40).stdout.decode()


@pytest.fixture
def ssh_server():
    name = 'orh-ssh-test-' + secrets.token_hex(5)
    image = os.environ.get('ORH_SSH_TEST_IMAGE', 'openremotehub/ssh-test:local')
    if subprocess.run(['docker', 'image', 'inspect', image], capture_output=True).returncode:
        pytest.skip('Build tests/fixtures/ssh/Dockerfile to run isolated live SSH tests')
    import socket
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = str(probe.getsockname()[1])
    docker('run', '-d', '--name', name, '-p', '127.0.0.1:' + port + ':22', image)
    try:
        for _ in range(40):
            if 'Server listening' in docker('logs', name) + subprocess.run(['docker', 'logs', name], capture_output=True).stderr.decode():
                break
            time.sleep(.1)
        yield name, port
    finally:
        docker('rm', '-f', name)


@pytest.fixture
def native_ssh_home(ssh_home, monkeypatch):
    client, directory, data = ssh_home
    monkeypatch.setattr(main, 'DB', data / 'metrics.sqlite3')
    with client:
        yield client, directory, data


def wait_job(token):
    for _ in range(100):
        result = jobs.get(token)
        if result['state'] not in ('queued', 'running'):
            return result
        time.sleep(.2)
    raise AssertionError('SSH job did not finish')


def scan_and_trust(client):
    result = hosts.scan('isolated')
    post(client, '/hosts/trust', dict(scan_id=result['scan_id'], confirm=result['label'],
         replace=bool(result['known']), grant=grant(client, 'host-update', 'isolated') if result['known'] else '', fingerprints=[key['fingerprint'] for key in result['keys']]))
    return result


@pytest.mark.live
def test_isolated_handshake_auth_key_rotation_and_cancel(ssh_home, ssh_server):
    client, directory, _ = ssh_home
    container, port = ssh_server
    post(client, '/keys/generate', dict(name='key', comment='isolated test'))
    add(client, 'isolated', port=port, user='tester', identityfile=str(directory / 'key'))
    link(client)
    first = wait_job(jobs.start('isolated')['id'])
    assert first['result']['status'] == 'host_key_error', first
    scan_and_trust(client)
    denied = wait_job(jobs.start('isolated')['id'])
    assert denied['result']['status'] in ('authentication_failed', 'interactive_required'), denied
    public = (directory / 'key.pub').read_bytes()
    docker('exec', '-i', container, 'sh', '-c', 'mkdir -p /home/tester/.ssh; cat > /home/tester/.ssh/authorized_keys; chown -R tester:tester /home/tester/.ssh; chmod 700 /home/tester/.ssh; chmod 600 /home/tester/.ssh/authorized_keys', input_data=public)
    authenticated = wait_job(jobs.start('isolated')['id'])
    assert authenticated['result']['status'] == 'authenticated', authenticated
    known = hosts.known('isolated')
    assert len(known['entries']) >= 1
    # Rotate only this disposable server's keys. StrictHostKeyChecking must block it.
    docker('exec', container, 'sh', '-c', 'rm /etc/ssh/ssh_host_*; ssh-keygen -A')
    docker('restart', container)
    for _ in range(50):
        import socket
        try:
            with socket.create_connection(('127.0.0.1', int(port)), timeout=.2) as probe:
                if probe.recv(256).startswith(b'SSH-'):
                    break
        except OSError:
            time.sleep(.1)
    changed = wait_job(jobs.start('isolated')['id'])
    assert changed['result']['status'] == 'host_key_error', changed
    scan = hosts.scan('isolated')
    assert scan['changed']
    scan_and_trust(client)
    assert wait_job(jobs.start('isolated')['id'])['result']['status'] == 'authenticated'
    cancelled = jobs.start('isolated')
    jobs.stop(cancelled['id'])
    assert wait_job(cancelled['id'])['state'] in ('cancelled', 'completed')


@pytest.mark.live
def test_password_public_key_deployment_over_tty_is_idempotent(ssh_home, ssh_server):
    client, directory, data = ssh_home
    container, port = ssh_server
    post(client, '/keys/generate', dict(name='deploy-key', passphrase='test-encrypted-key'))
    add(client, 'isolated', port=port, user='tester')
    link(client)
    scan_and_trust(client)

    def deploy_once():
        token = secrets.token_hex(8)
        store.put('terminal', token, dict(host='isolated', session='unused-fixture', key='deploy-key',
                   signature=__import__('app.ssh.configuration', fromlist=['discover']).discover()['signature'],
                   created=time.time(), state='starting'))
        pid, master = pty.fork()
        if pid == 0:
            os.execv(sys.executable, [sys.executable, str(main.ROOT / 'scripts/ssh_terminal.py'), '--data', str(data),
                                     '--ssh-dir', str(directory), '--launch', token])
        transcript = ''
        answered = 0
        end = time.monotonic() + 25
        try:
            while time.monotonic() < end:
                readable, _, _ = select.select([master], [], [], .1)
                if readable:
                    try:
                        raw = os.read(master, 16384)
                    except OSError:
                        break
                    if not raw:
                        break
                    transcript += raw.decode(errors='replace')
                    if transcript.lower().rstrip().endswith('password:'):
                        os.write(master, b'orh-isolated-fixture-password\n')
                        transcript = ''
                        answered += 1
                    elif 'passphrase for key' in transcript.lower() and transcript.rstrip().endswith(':'):
                        os.write(master, b'test-encrypted-key\n')
                        transcript = ''
                        answered += 1
            else:
                raise AssertionError('Interactive deployment timed out')
            _, status = os.waitpid(pid, 0)
            assert os.waitstatus_to_exitcode(status) == 0, transcript
            assert answered >= 1
            assert store.get('terminal', token)['state'] == 'completed'
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
            os.close(master)
    deploy_once()
    deploy_once()
    content = docker('exec', container, 'cat', '/home/tester/.ssh/authorized_keys')
    blob = (directory / 'deploy-key.pub').read_text().split()[1]
    assert content.count(blob) == 1
    modes = docker('exec', container, 'stat', '-c', '%a', '/home/tester/.ssh', '/home/tester/.ssh/authorized_keys').splitlines()
    assert modes == ['700', '600']
    for path in data.rglob('*'):
        if path.is_file():
            assert b'orh-isolated-fixture-password' not in path.read_bytes()
            assert b'test-encrypted-key' not in path.read_bytes()


@pytest.mark.live
def test_native_zellij_owned_ssh_reuse_disconnect_and_explicit_reconnect(native_ssh_home, ssh_server, monkeypatch):
    client, directory, data = native_ssh_home
    container, port = ssh_server
    if not (REAL_DATA / 'zellij-gateway.json').exists():
        pytest.skip('Native Zellij gateway must be initialized')
    (data / 'zellij-gateway.json').write_bytes((REAL_DATA / 'zellij-gateway.json').read_bytes())
    (data / 'zellij-gateway.json').chmod(0o600)
    monkeypatch.setattr(native_terminal, 'upstream', native_terminal.Upstream())
    post(client, '/keys/generate', dict(name='key'))
    add(client, 'isolated', port=port, user='tester', identityfile=str(directory / 'key'))
    link(client)
    scan_and_trust(client)
    docker('exec', '-i', container, 'sh', '-c', 'mkdir -p /home/tester/.ssh; cat > /home/tester/.ssh/authorized_keys; chown -R tester:tester /home/tester/.ssh; chmod 700 /home/tester/.ssh; chmod 600 /home/tester/.ssh/authorized_keys', input_data=(directory / 'key.pub').read_bytes())
    names = []
    try:
        first = post(client, '/connections/isolated/connect', {})
        names.append(first['session'])
        for _ in range(40):
            records = terminals.sessions()
            if any(row['running'] and row.get('pid') for row in records):
                break
            time.sleep(.15)
        else:
            raise AssertionError('SSH runner did not start in Zellij')
        assert post(client, '/connections/isolated/connect', {})['session'] == first['session']
        origin = f'https://127.0.0.1:{main.PORT}'
        headers = {'Origin': origin, 'Host': f'127.0.0.1:{main.PORT}'}
        url = origin.replace('https:', 'wss:') + '/terminal/ws/'
        def attach(stack):
            bootstrap = client.post('/terminal/session?session=' + first['session'], headers=headers)
            assert bootstrap.status_code == 200, bootstrap.text
            identifier = bootstrap.json()['web_client_id']
            terminal = stack.enter_context(client.websocket_connect(url + 'terminal/' + first['session'] + '?web_client_id=' + identifier + '&rows=24&cols=100', headers=headers))
            control = stack.enter_context(client.websocket_connect(url + 'control?web_client_id=' + identifier, headers=headers))
            control.send_json({'web_client_id': identifier, 'payload': {'type': 'TerminalResize', 'rows':24, 'cols':100}})
            return terminal
        with contextlib.ExitStack() as stack:
            term = attach(stack)
            attach(stack)
            time.sleep(.4)
            term.send_text("printf 'SSH_NATIVE_FIXTURE\\n'; sleep 2")
            term.send_text('\r')
        assert any(row['running'] and row['session'] == first['session'] for row in terminals.sessions())
        # A new Upstream instance models the console process restarting. Metadata,
        # cookie session, actual SSH process and Zellij session all remain durable.
        import asyncio
        client.portal.call(native_terminal.upstream.close)
        monkeypatch.setattr(native_terminal, 'upstream', native_terminal.Upstream())
        with contextlib.ExitStack() as stack:
            attach(stack)
        second = post(client, '/connections/isolated/connect', {'new': True})
        names.append(second['session'])
        assert second['session'] != first['session']
        panes = json.loads(main.cli(['zellij', '--session', first['session'], 'action', 'list-panes', '--all', '--json'], 4))
        pane = next(p for p in panes if not p['is_plugin'] and 'ssh_terminal.py' in p.get('terminal_command', ''))
        pane_id = 'terminal_' + str(pane['id'])
        main.cli(['zellij', '--session', first['session'], 'action', 'write-chars', '--pane-id', pane_id, 'exit'], 4)
        main.cli(['zellij', '--session', first['session'], 'action', 'write', '--pane-id', pane_id, '13'], 4)
        for _ in range(60):
            record = next(row for row in terminals.sessions() if row['session'] == first['session'])
            if not record['running']:
                break
            time.sleep(.1)
        assert not record['running'], main.cli(['zellij', '--session', first['session'], 'action', 'dump-screen', '--pane-id', pane_id], 4)
        third = post(client, '/connections/isolated/connect', {})
        assert third['session'] == second['session']
    finally:
        from app.zellij_manage import mutate
        for name in names:
            mutate(name, 'purge')
        import asyncio
        client.portal.call(native_terminal.upstream.close)


@pytest.mark.live
def test_real_proxyjump_preserves_strict_host_verification(ssh_home, ssh_server):
    client, directory, _ = ssh_home
    container, port = ssh_server
    post(client, '/keys/generate', dict(name='jump-key'))
    public = (directory / 'jump-key.pub').read_bytes()
    docker('exec', '-i', container, 'sh', '-c', 'mkdir -p /home/tester/.ssh; cat > /home/tester/.ssh/authorized_keys; chown -R tester:tester /home/tester/.ssh; chmod 700 /home/tester/.ssh; chmod 600 /home/tester/.ssh/authorized_keys', input_data=public)
    add(client, 'jump', port=port, user='tester', identityfile=str(directory / 'jump-key'))
    add(client, 'jumped', port='22', user='tester', proxyjump='jump', identityfile=str(directory / 'jump-key'))
    link(client)
    # Even an unsafe original hop setting must not disable the managed policy.
    with (directory / 'config').open('a') as stream:
        stream.write('\nHost jump\n StrictHostKeyChecking no\n')
    scan = hosts.scan('jump')
    # Target is the same disposable SSH server, reached from the jump's loopback.
    # Validate the advertised ED25519 key independently through Docker first.
    independent = docker('exec', container, 'cat', '/etc/ssh/ssh_host_ed25519_key.pub').split()[:2]
    verified = next(key for key in scan['keys'] if key['public'].split()[:2] == independent)
    (directory / 'known_hosts').write_text('127.0.0.1 ' + verified['public'] + '\n[127.0.0.1]:' + port + ' ' + public.decode().strip() + '\n')
    denied = wait_job(jobs.start('jumped')['id'])
    assert denied['result']['status'] == 'host_key_error', denied
    scan = hosts.scan('jump')
    post(client, '/hosts/trust', dict(scan_id=scan['scan_id'], confirm=scan['label'], replace=True, grant=grant(client, 'host-update', 'jump'), fingerprints=[key['fingerprint'] for key in scan['keys']]))
    result = wait_job(jobs.start('jumped')['id'])
    assert result['result']['status'] == 'authenticated', result
