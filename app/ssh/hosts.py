"""Untrusted key scans and explicit, revision-checked known_hosts changes."""
import time
import secrets

from fastapi import HTTPException
from app.ssh import configuration as config, storage as store
from app.ssh.keys import public_line
from app.ssh.process import run, CommandFailure


def address(host, cancel=None):
    values = config.effective(host, cancel=cancel)
    hostname = values.get('hostname', host)
    port = values.get('port', '22')
    import re
    if not re.fullmatch(r'[A-Za-z0-9:][A-Za-z0-9.:%_-]{0,252}', hostname) or not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise HTTPException(400, '生效的 SSH 地址或端口无效')
    label = values.get('hostkeyalias') or (hostname if port == '22' else f'[{hostname}]:{port}')
    return hostname, port, label, values


def matching(label, content):
    """ssh-keygen handles hashed hosts and OpenSSH host patterns."""
    if not content:
        return []
    from app.ssh.keys import staging
    with staging() as temp:
        temp.write_bytes(content)
        temp.chmod(0o600)
        try:
            output = run(['ssh-keygen', '-F', label, '-f', str(temp)])
        except CommandFailure as error:
            if error.code == 1:
                return []
            raise HTTPException(400, 'known_hosts 格式无法读取') from None
    entries = []
    line_number = None
    for line in output.splitlines():
        if line.startswith('# Host ') and 'found: line ' in line:
            line_number = int(line.strip().rsplit(' ', 1)[1])
        elif line and not line.startswith('#'):
            parts = line.split()
            marker = parts.pop(0) if parts[0].startswith('@') else ''
            try:
                info = public_line(' '.join(parts[1:]))
            except HTTPException:
                continue
            entries.append(dict(info, line=line_number, marker=marker, hosts=parts[0]))
    return entries


def known(host, cancel=None):
    hostname, port, label, values = address(host, cancel)
    content = store.read(store.path('known_hosts'))
    paths = values.get('userknownhostsfile', [])
    outside = [p for value in paths for p in value.split() if p not in (str(store.path('known_hosts')), '~/.ssh/known_hosts', 'none')]
    return dict(host=host, hostname=hostname, port=int(port), label=label,
                entries=matching(label, content), revision=store.digest(content), external_files=outside)


def scan(host, cancel=None):
    hostname, port, label, values = address(host, cancel)
    if values.get('proxyjump', 'none') != 'none':
        raise HTTPException(409, '此连接使用跳板，请在原生终端中核验 OpenSSH 显示的指纹；自动扫描只支持直连地址')
    try:
        output = run(['ssh-keyscan', '-T', '5', '-p', port, hostname], timeout=18, cancel=cancel)
    except CommandFailure:
        raise HTTPException(502, '未收到 SSH 主机公钥，请检查地址、端口与网络') from None
    found = {}
    for line in output.splitlines():
        if line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) >= 3:
            try:
                info = public_line(' '.join(parts[1:]))
                found[info['fingerprint']] = info
            except HTTPException:
                continue
    if not found:
        raise HTTPException(502, '目标未返回可识别的主机公钥')
    token = secrets.token_hex(16)
    state = known(host, cancel)
    result = dict(host=host, label=label, keys=list(found.values()), expires=time.time() + 300,
                  revision=state['revision'], signature=config.discover()['signature'])
    store.put('scan', token, result)
    changed = bool(state['entries']) and any(e['fingerprint'] not in found for e in state['entries'] if e['marker'] != '@cert-authority')
    return dict(result, scan_id=token, known=state['entries'], changed=changed)


def trust(body):
    with store.locked():
        scan = store.get('scan', body.get('scan_id'))
        if not scan or scan['expires'] < time.time() or scan['signature'] != config.discover()['signature']:
            raise HTTPException(409, '扫描结果已失效，请重新扫描并核验')
        if body.get('confirm') != scan['label']:
            raise HTTPException(400, '请明确确认目标主机指纹')
        old = store.read(store.path('known_hosts'))
        if store.digest(old) != scan['revision']:
            raise HTTPException(409, 'known_hosts 已改变，请重新扫描')
        existing = matching(scan['label'], old)
        if existing and not body.get('replace'):
            raise HTTPException(409, '已有主机指纹，请核验并选择更新指纹')
        selected = set(body.get('fingerprints', []))
        keys = [k for k in scan['keys'] if k['fingerprint'] in selected]
        if not keys:
            raise HTTPException(400, '请至少选择一个已核验指纹')
        content = remove_lines(old, existing, scan['label']) if existing else old
        if content and not content.endswith(b'\n'):
            content += b'\n'
        content += ''.join(scan['label'] + ' ' + k['public'] + '\n' for k in keys).encode()
        result = store.write('known_hosts', content, scan['revision'])
        store.remove('scan', scan['id'])
        return result


def remove_lines(content, entries, label):
    targets = {e['line'] for e in entries}
    output = []
    for number, line in enumerate(content.decode().splitlines(True), 1):
        if number not in targets:
            output.append(line)
            continue
        parts = line.split()
        offset = 1 if parts[0].startswith('@') else 0
        # A comma-separated shared record must retain its other host names.
        names = parts[offset].split(',')
        if names[0].startswith('|'):
            continue
        if label in names:
            names.remove(label)
            if names:
                parts[offset] = ','.join(names)
                output.append(' '.join(parts) + '\n')
        else:
            parts[offset] = ','.join(['!' + label] + names)
            output.append(' '.join(parts) + '\n')
    return ''.join(output).encode()


def remove(host, expected):
    with store.locked():
        state = known(host)
        if state['revision'] != expected:
            raise HTTPException(409, '指纹记录已修改，请刷新')
        old = store.read(store.path('known_hosts'))
        return store.write('known_hosts', remove_lines(old, state['entries'], state['label']), expected)
