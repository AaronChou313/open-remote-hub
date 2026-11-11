"""Owned Zellij sessions, with immutable launch descriptors and explicit retries."""
import os
from pathlib import Path
import secrets
import sys
import threading
import time

from fastapi import HTTPException
from app.ssh import configuration as config, storage as store

mutex = threading.RLock()


def connection(host):
    config.alias(host)
    inventory = config.inventory()
    found = next((r for r in inventory['connections'] if r['alias'].lower() == host.lower()), None)
    if found and found['managed'] and not inventory['linked']:
        raise HTTPException(409, '请先在 SSH 配置标签页接入原生 Config')
    if not found:
        raise HTTPException(404, 'SSH 连接不存在')
    config.checked_sources()
    return config.effective(host)


def argv(host, interactive=True, identity=None):
    command = ['ssh'] + config.native_arguments(interactive) + ['-o', 'PermitLocalCommand=no',
               '-o', 'RemoteCommand=none', '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
               '-o', 'StrictHostKeyChecking=' + ('ask' if interactive else 'yes'),
               '-o', 'ConnectTimeout=10', '-o', 'ConnectionAttempts=1']
    if store.root() != Path.home() / '.ssh':
        command += ['-o', 'UserKnownHostsFile=' + config.quote(str(store.path('known_hosts'))), '-o', 'GlobalKnownHostsFile=none']
    if not interactive:
        command += ['-o', 'BatchMode=yes']
    if identity:
        from app.ssh.keys import key_name
        key_name(identity)
        store.read(store.path(identity), private=True)
        command += ['-i', str(store.path(identity)), '-o', 'IdentitiesOnly=yes', '-o', 'PubkeyAuthentication=yes']
    return command + ['--', config.alias(host)]


def sessions():
    from app.zellij_sessions import host_sessions
    actual = {s['name']: s for s in host_sessions()}
    result = []
    for row in store.rows('terminal'):
        if row.get('pid') and row.get('state') == 'running':
            import psutil
            try:
                process = psutil.Process(row['pid'])
                if abs(process.create_time() - row['process_created']) < .01:
                    ancestors = {parent.pid for parent in process.parents()}
                    renamed = next((entry for entry in actual.values() if entry.get('pid') in ancestors), None)
                    if renamed and renamed['name'] != row['session']:
                        row['session'] = renamed['name']
                        store.put('terminal', row['id'], row)
            except (psutil.Error, KeyError):
                pass
        active = actual.get(row['session'], {}).get('status') == 'running'
        # A live Zellij shell alone is not proof an SSH process is still connected.
        running = active and row.get('state') in ('starting', 'running')
        if row.get('state') == 'starting' and time.time() - row['created'] > 30:
            running = False
        if running and row.get('pid'):
            import psutil
            try:
                process = psutil.Process(row['pid'])
                running = process.is_running() and process.status() != psutil.STATUS_ZOMBIE and abs(process.create_time() - row['process_created']) < .01
            except (psutil.Error, KeyError):
                running = False
        result.append(dict(row, running=running, live_session=active))
    return result


def launch(host, new=False, key=None):
    from app import main
    from app.terminal_entry import ensure_web
    from app.zellij_sessions import host_sessions
    values = connection(host)
    signature = config.discover()['signature']
    if key:
        from app.ssh.keys import key_name, public_line
        key_name(key)
        public_line(store.read(store.path(key + '.pub')).decode())
        if not store.read(store.path(key), private=True):
            raise HTTPException(400, '部署后验证需要对应的本地私钥')
    with mutex:
        if not new and not key:
            existing = next((s for s in sessions() if s['host'].lower() == host.lower() and s['running']
                             and s['signature'] == signature and not s.get('key')), None)
            if existing:
                ensure_web()
                return dict(session=existing['session'], url='/terminal/' + existing['session'], reused=True)
        ensure_web()
        token = secrets.token_hex(8)
        name = 'ssh-' + token[:12]
        # Never resurrect a name or insert commands into an existing pane.
        if any(s['name'] == name for s in host_sessions()):
            raise HTTPException(409, '会话名称冲突，请重试')
        row = dict(host=host, session=name, key=key, signature=signature, created=time.time(),
                   state='starting', hostname=values.get('hostname'), port=values.get('port'))
        store.put('terminal', token, row)
        command = ['zellij', '--config', str(main.ROOT / 'config/zellij.kdl'), 'attach',
                   '--create-background', name, '--', sys.executable, str(main.ROOT / 'scripts/ssh_terminal.py'),
                   '--data', str(main.DATA), '--ssh-dir', str(store.root()), '--launch', token]
        try:
            main.cli(command, 10, cwd=str(Path.home()))
        except Exception:
            latest = store.get('terminal', token)
            if latest and latest['state'] == 'starting':
                latest['state'] = 'launch_failed'
                store.put('terminal', token, latest)
            raise
        main.audit('ssh', host, 'deploy-terminal' if key else 'connect-terminal')
        return dict(session=name, url='/terminal/' + name, reused=False)
