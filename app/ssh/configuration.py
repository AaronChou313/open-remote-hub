"""Discover Host names, delegate effective semantics to system OpenSSH."""
import difflib
import fnmatch
import glob
import json
import os
from pathlib import Path
import re
import shlex

from fastapi import HTTPException
from app.ssh import storage as store
from app.ssh.process import run, CommandFailure

MANAGED = 'openremotehub.conf'
FIELDS = {'hostname': 'HostName', 'port': 'Port', 'user': 'User', 'identityfile': 'IdentityFile',
          'proxyjump': 'ProxyJump', 'identityagent': 'IdentityAgent', 'forwardagent': 'ForwardAgent',
          'identitiesonly': 'IdentitiesOnly'}


def alias(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', value):
        raise HTTPException(400, '连接别名只允许字母、数字、点、横线和下划线')
    return value


def tokens(line):
    lexer = shlex.shlex(line, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = '#'
    try:
        result = list(lexer)
    except ValueError:
        raise HTTPException(400, 'SSH 配置含未闭合引号') from None
    if result and '=' in result[0]:
        key, value = result[0].split('=', 1)
        result = [key, value] + result[1:]
    elif len(result) > 1 and result[1] == '=':
        result.pop(1)
    return result


def discover():
    files, hosts, rules, warnings = [], {}, [], []
    visited = set()

    def visit(path, depth=0):
        path = Path(os.path.abspath(path))
        if str(path) in visited:
            return
        if depth > 16 or len(visited) >= 128:
            raise HTTPException(400, 'SSH Include 超过深度或文件数量上限')
        visited.add(str(path))
        try:
            content = store.read(path)
            text = content.decode('utf-8')
        except (HTTPException, UnicodeError):
            warnings.append('部分 Include 文件因权限、软链接或编码无法读取')
            return
        if b'PRIVATE KEY-----' in content or b'\x00' in content:
            warnings.append('Include 含非 SSH 配置内容，已阻止通过配置接口读取')
            return
        if not content and not path.exists():
            return
        inside = path.is_relative_to(store.root())
        file_id = store.digest(str(path).encode())[:24]
        dynamic = False
        for number, line in enumerate(text.splitlines(), 1):
            parts = tokens(line)
            if not parts:
                continue
            key = parts[0].lower()
            if key == 'include':
                for pattern in parts[1:]:
                    expanded = os.path.expanduser(pattern)
                    if not os.path.isabs(expanded):
                        expanded = str(store.root() / expanded)
                    for child in sorted(glob.glob(expanded)):
                        visit(child, depth + 1)
            if key == 'match' and 'exec' in [p.lower().lstrip('!') for p in parts[1:]]:
                dynamic = True
            if key in ('proxycommand', 'localcommand', 'knownhostscommand'):
                dynamic = True
            if key == 'host':
                for item in parts[1:]:
                    if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', item):
                        host = hosts.setdefault(item.lower(), dict(alias=item, sources=[]))
                        host['sources'].append(dict(file=file_id, line=number, managed=path == store.path(MANAGED)))
                    else:
                        rules.append(dict(pattern=item, file=file_id, line=number))
        files.append(dict(id=file_id, path=str(path), name=path.name, revision=store.digest(content),
                          editable=inside and path != store.path(MANAGED), dynamic=dynamic,
                          relative=str(path.relative_to(store.root())) if inside else None))

    visit(store.path('config'))
    if store.path(MANAGED).exists() and str(store.path(MANAGED)) not in visited:
        visit(store.path(MANAGED))
    signature = store.digest(json.dumps(sorted((f['path'], f['revision']) for f in files)).encode())
    trusted = store.get('trust-config', signature) is not None
    return dict(hosts=list(hosts.values()), files=files, rules=rules, warnings=sorted(set(warnings)),
                signature=signature, requires_trust=any(f['dynamic'] for f in files) and not trusted)


def assert_trusted():
    result = discover()
    if result['requires_trust']:
        raise HTTPException(409, '原生配置含 Match exec 或命令指令，请先在 SSH 配置中核验并授权当前版本')
    return result


def quote(value):
    if any(c in value for c in '\r\n\x00') or len(value) > 512:
        raise HTTPException(400, 'SSH 配置字段含无效字符或过长')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def normalized(body):
    result = dict(alias=alias(body.get('alias')), group=str(body.get('group', '')).strip()[:80],
                  favorite=bool(body.get('favorite', False)))
    for key in FIELDS:
        value = str(body.get(key, '')).strip()
        if not value:
            continue
        if key == 'port':
            if not value.isdecimal() or not 1 <= int(value) <= 65535:
                raise HTTPException(400, 'SSH 端口范围为 1–65535')
        elif key in ('forwardagent', 'identitiesonly'):
            if value not in ('yes', 'no'):
                raise HTTPException(400, 'Agent 设置必须为 yes 或 no')
        elif key == 'hostname':
            if not re.fullmatch(r'[A-Za-z0-9:][A-Za-z0-9.:%_-]{0,252}', value):
                raise HTTPException(400, '主机地址无效')
        elif key == 'user':
            if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]{0,79}', value):
                raise HTTPException(400, 'SSH 用户名无效')
        elif key == 'proxyjump':
            if value != 'none' and not re.fullmatch(r'[A-Za-z0-9_\[\].:@,%+-]{1,512}', value):
                raise HTTPException(400, 'ProxyJump 格式无效')
        elif key == 'identityfile':
            candidate = Path(value.replace('~/', str(Path.home()) + '/', 1)).absolute()
            if candidate.parent != store.root() or candidate.name in ('config', MANAGED, 'known_hosts'):
                raise HTTPException(403, '请选择 SSH 管理目录内的密钥')
            store.read(candidate, private=True)
        elif key == 'identityagent':
            if value not in ('none', 'SSH_AUTH_SOCK'):
                candidate = Path(value).expanduser()
                if not candidate.is_absolute() or '..' in candidate.parts or '%' in value:
                    raise HTTPException(400, 'Agent 使用 none、SSH_AUTH_SOCK 或绝对 Socket 路径')
        quote(value)
        result[key] = value
    return result


def render(rows):
    lines = ['# Managed by OpenRemoteHub. Edit connections in the Web console.']
    for row in sorted(rows, key=lambda r: r['alias'].lower()):
        lines.append('\nHost ' + alias(row['alias']))
        for key, native in FIELDS.items():
            if row.get(key):
                lines.append('    ' + native + ' ' + quote(str(row[key])))
    # An included file must not leak its final Host context into the parent.
    lines.append('\nHost *\n')
    return '\n'.join(lines).encode()


def include_plan():
    old = store.read(store.path('config')).decode('utf-8')
    line = 'Include ' + quote(str(store.path(MANAGED))) + '\n'
    # Keep the owned Include first because OpenSSH uses the first obtained value.
    remaining = []
    for original in old.splitlines(keepends=True):
        parts = tokens(original)
        if parts and parts[0].lower() == 'include' and len(parts) == 2:
            expanded = Path(os.path.expanduser(parts[1]))
            if not expanded.is_absolute():
                expanded = store.root() / expanded
            if expanded == store.path(MANAGED):
                continue
        remaining.append(original)
    new = line + ''.join(remaining)
    return dict(file='config', text=new, revision=store.digest(old.encode()), diff=diff(old, new), linked=old == new)


def diff(old, new):
    return ''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile='当前版本', tofile='保存后'))


def native_arguments():
    if store.root() == Path.home() / '.ssh':
        return []
    return ['-F', str(store.path('config'))]


def effective(host):
    alias(host)
    assert_trusted()
    try:
        output = run(['ssh', '-G'] + native_arguments() + ['--', host])
    except CommandFailure:
        raise HTTPException(400, 'OpenSSH 无法求值此配置，请检查 SSH 配置语法') from None
    values = {}
    for line in output.splitlines():
        key, _, value = line.partition(' ')
        values.setdefault(key, []).append(value)
    # Never return commands, tokens, arbitrary environment values or config dumps.
    allowed = ('hostname', 'user', 'port', 'identityfile', 'identityagent', 'proxyjump', 'forwardagent',
               'identitiesonly', 'stricthostkeychecking', 'userknownhostsfile')
    return {key: (values[key] if key in ('identityfile', 'userknownhostsfile') else values[key][0])
            for key in allowed if key in values}


def inventory():
    recover()
    result = discover()
    owned = {r['alias'].lower(): r for r in store.rows('connection')}
    metadata = {r['id']: r for r in store.rows('host-meta')}
    entries = []
    for host in result['hosts']:
        key = host['alias'].lower()
        managed = owned.pop(key, None)
        entries.append(dict(host, **{k: v for k, v in (managed or {}).items() if k != 'alias'},
                            managed=managed is not None,
                            duplicate=len(host['sources']) > 1,
                            metadata=metadata.get(key, {})))
    for row in owned.values():
        entries.append(dict(row, managed=True, sources=[], duplicate=False, metadata={}))
    return dict(result, connections=sorted(entries, key=lambda r: r['alias'].lower()),
                managed_revision=store.revision(MANAGED), linked=include_plan()['linked'])


def save_connection(body):
    with store.locked():
        recover()
        row = normalized(body)
        old_alias = body.get('original_alias')
        entries = store.rows('connection')
        existing = next((r for r in entries if r['alias'].lower() == str(old_alias).lower()), None)
        if old_alias and not existing:
            raise HTTPException(404, '受管连接不存在')
        if old_alias and body.get('connection_revision') != existing.get('revision'):
            raise HTTPException(409, '连接已被修改，请重新打开')
        for host in discover()['hosts']:
            same = existing and host['alias'].lower() == existing['alias'].lower()
            if host['alias'].lower() == row['alias'].lower() and (not same or any(not s['managed'] for s in host['sources'])):
                raise HTTPException(409, '此 Host 已存在于 SSH 配置，请使用其他别名或高级编辑')
        if any(r['alias'].lower() == row['alias'].lower() and r != existing for r in entries):
            raise HTTPException(409, '连接别名重复')
        # Protect against manual edits to the owned file as well as stale browsers.
        expected = body.get('managed_revision')
        previous = store.read(store.path(MANAGED))
        if previous and previous != render(entries):
            raise HTTPException(409, 'openremotehub.conf 已在外部修改，请先在配置页面查看并处理差异')
        row['revision'] = store.digest(json.dumps(row, sort_keys=True).encode())
        updated = [r for r in entries if r != existing] + [row]
        result = commit_connections(updated, expected)
        return dict(row, file=result)


def delete_connection(host, expected, connection_revision):
    with store.locked():
        row = store.get('connection', host.lower())
        if not row:
            raise HTTPException(404, '只能直接删除 OpenRemoteHub 管理的连接，外部条目请使用高级编辑')
        if row.get('revision') != connection_revision:
            raise HTTPException(409, '连接已修改，请刷新')
        entries = store.rows('connection')
        if store.read(store.path(MANAGED)) != render(entries):
            raise HTTPException(409, '受管文件在外部修改，删除已取消')
        result = commit_connections([r for r in entries if r['id'] != row['id']], expected)
        return result


def commit_connections(entries, expected):
    current = store.revision(MANAGED)
    if expected != current:
        raise HTTPException(409, '受管配置已改变，请刷新')
    content = render(entries)
    store.put('transaction', 'connections', dict(before=current, after=store.digest(content), entries=entries))
    result = store.write(MANAGED, content, expected)
    recover()
    return result


def recover():
    """Reconcile a crash between the file rename and metadata transaction."""
    with store.locked():
        pending = store.get('transaction', 'connections')
        if not pending:
            return
        revision = store.revision(MANAGED)
        if revision == pending['after']:
            with store.connect() as db:
                db.execute('DELETE FROM records WHERE kind=?', ('connection',))
                for entry in pending['entries']:
                    row = {k: v for k, v in entry.items() if k != 'id'}
                    db.execute('INSERT INTO records VALUES (?,?,?)', ('connection', row['alias'].lower(), json.dumps(row)))
                db.execute('DELETE FROM records WHERE kind=? AND id=?', ('transaction', 'connections'))
        elif revision == pending['before']:
            store.remove('transaction', 'connections')
        else:
            raise HTTPException(409, '受管配置在中断操作后被外部修改，请从备份恢复后再继续')


def validate(key, text):
    """Ask OpenSSH to parse a private mirror, replacing only executable Match tests.

    Includes are absolute mirror paths so validation cannot run newly supplied
    Match exec directives. Native rules in real files are left intact on disk.
    """
    import tempfile
    with tempfile.TemporaryDirectory(prefix='orh-ssh-validate-') as folder:
        base = Path(folder)
        mirrored = {}
        total = 0

        def copy(source, depth=0):
            nonlocal total
            source = Path(os.path.abspath(source))
            if source in mirrored:
                return mirrored[source]
            if depth > 16 or len(mirrored) >= 128:
                raise HTTPException(400, '配置 Include 超过验证上限')
            destination = base / (str(len(mirrored)) + '.conf')
            mirrored[source] = destination
            if source == store.path(key):
                value = text
            elif source == store.path(MANAGED) and not source.exists():
                value = render(store.rows('connection')).decode()
            else:
                value = store.read(source).decode()
            if 'PRIVATE KEY-----' in value or '\x00' in value:
                raise HTTPException(400, 'Include 包含非 SSH 配置内容')
            total += len(value.encode())
            if total > 8 * 1024 * 1024:
                raise HTTPException(413, 'Include 配置总量超过 8 MiB')
            lines = []
            for line in value.splitlines():
                parts = tokens(line)
                if parts and parts[0].lower() == 'include':
                    targets = []
                    for pattern in parts[1:]:
                        expanded = os.path.expanduser(pattern)
                        if not os.path.isabs(expanded):
                            expanded = str(Path.home() / '.ssh' / expanded)
                        candidates = glob.glob(expanded)
                        if Path(expanded) == store.path(MANAGED) and not candidates:
                            candidates = [expanded]
                        targets.extend(quote(str(copy(child, depth + 1))) for child in sorted(candidates))
                    line = 'Include ' + ' '.join(targets) if targets else '# Unmatched Include'
                elif parts and parts[0].lower() == 'match':
                    for index, part in enumerate(parts[:-1]):
                        if part.lower().lstrip('!') == 'exec':
                            parts[index + 1] = 'false'
                    line = ' '.join(quote(part) for part in parts)
                lines.append(line)
            destination.write_text('\n'.join(lines) + '\n')
            destination.chmod(0o600)
            return destination

        entry = copy(store.path('config'))
        # Validate a directly edited include even if its Host/Match is inactive.
        direct = copy(store.path(key))
        for candidate in dict.fromkeys((entry, direct)):
            try:
                run(['ssh', '-G', '-F', str(candidate), '-o', 'CanonicalizeHostname=no', '--', 'orh-config-validation'])
            except CommandFailure:
                raise HTTPException(400, 'OpenSSH 配置语法校验失败，当前文件未修改') from None
