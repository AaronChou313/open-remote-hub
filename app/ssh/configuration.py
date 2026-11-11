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


def read_source(path):
    """Follow native Include links for read-only inspection, then pin the target.

    Linked sources cannot be edited through the config API. Their canonical
    destination and content digest participate in the authorization signature.
    """
    try:
        canonical = Path(path).resolve(strict=True)
    except FileNotFoundError:
        return Path(path).absolute(), b''
    except (OSError, RuntimeError):
        raise HTTPException(403, 'SSH Include 路径无法安全解析') from None
    return canonical, store.read(canonical, allow_root=True)


def discover():
    files, hosts, rules, warnings = [], {}, [], []
    unverified = []
    visited = set()

    def visit(path, depth=0):
        path = Path(os.path.abspath(path))
        if str(path) in visited:
            return
        if depth > 16 or len(visited) >= 128:
            raise HTTPException(400, 'SSH Include 超过深度或文件数量上限')
        visited.add(str(path))
        try:
            canonical, content = read_source(path)
            text = content.decode('utf-8')
        except (HTTPException, UnicodeError):
            warnings.append('部分 Include 文件因权限或编码无法读取')
            unverified.append(str(path))
            return
        if b'PRIVATE KEY-----' in content or b'\x00' in content:
            warnings.append('Include 含非 SSH 配置内容，已阻止通过配置接口读取')
            unverified.append(str(path))
            return
        if not content and not path.exists():
            return
        inside = path.is_relative_to(store.root()) and canonical == path and path.stat().st_uid == os.getuid()
        file_id = store.digest(str(path).encode())[:24]
        dynamic = False
        for number, line in enumerate(text.splitlines(), 1):
            try:
                parts = tokens(line)
            except HTTPException:
                warnings.append('部分配置行引号不完整，请在高级编辑中修正')
                unverified.append(str(path) + ':' + str(number))
                continue
            if not parts:
                continue
            key = parts[0].lower()
            if key == 'include':
                for pattern in parts[1:]:
                    expanded = os.path.expanduser(pattern)
                    if not os.path.isabs(expanded):
                        expanded = str(Path.home() / '.ssh' / expanded)
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
        files.append(dict(id=file_id, path=str(path), read_path=str(canonical), name=path.name, revision=store.digest(content),
                          editable=inside and path != store.path(MANAGED), dynamic=dynamic,
                          relative=str(path.relative_to(store.root())) if inside else None))

    visit(store.path('config'))
    if store.path(MANAGED).exists() and str(store.path(MANAGED)) not in visited:
        visit(store.path(MANAGED))
    signature = store.digest(json.dumps(sorted((f['path'], f['read_path'], f['revision']) for f in files)).encode())
    return dict(hosts=list(hosts.values()), files=files, rules=rules, warnings=sorted(set(warnings)),
                signature=signature, unverified_sources=unverified, has_command_rules=any(f['dynamic'] for f in files))


def checked_sources():
    result = discover()
    if result['unverified_sources']:
        raise HTTPException(409, '部分 SSH Include 无法核验，请先在 SSH 配置中修复路径、语法或文件权限')
    return result


def quote(value):
    if any(c in value for c in '\r\n\x00') or len(value) > 512:
        raise HTTPException(400, 'SSH 配置字段含无效字符或过长')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def normalized(body):
    result = dict(alias=alias(body.get('alias')), group=str(body.get('group', '')).strip()[:80],
                  favorite=bool(body.get('favorite', False)))
    authentication = body.get('authentication', 'auto')
    if authentication not in ('auto', 'password', 'key'):
        raise HTTPException(400, '请选择密码或密钥认证方式')
    if authentication != 'auto':
        result['authentication'] = authentication
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
        if row.get('authentication') == 'password':
            lines.extend(['    PreferredAuthentications keyboard-interactive,password',
                          '    PubkeyAuthentication no', '    PasswordAuthentication yes',
                          '    KbdInteractiveAuthentication yes'])
        elif row.get('authentication') == 'key':
            lines.extend(['    PreferredAuthentications publickey', '    PubkeyAuthentication yes'])
        for key, native in FIELDS.items():
            if row.get(key):
                lines.append('    ' + native + ' ' + quote(str(row[key])))
    # An included file must not leak its final Host context into the parent.
    lines.append('\nHost *\n')
    return '\n'.join(lines).encode()


def include_plan():
    canonical, content = read_source(store.path('config'))
    old = content.decode('utf-8')
    line = 'Include ' + quote(str(store.path(MANAGED))) + '\n'
    # Keep the owned Include first because OpenSSH uses the first obtained value.
    remaining = []
    for original in old.splitlines(keepends=True):
        try:
            parts = tokens(original)
        except HTTPException:
            remaining.append(original)
            continue
        if parts and parts[0].lower() == 'include' and len(parts) == 2:
            expanded = Path(os.path.expanduser(parts[1]))
            if not expanded.is_absolute():
                expanded = store.root() / expanded
            if expanded == store.path(MANAGED):
                continue
        remaining.append(original)
    new = line + ''.join(remaining)
    return dict(file='config', text=new, revision=store.digest(old.encode()), diff=diff(old, new), linked=old == new, read_only=canonical != store.path('config') or (store.path('config').exists() and canonical.stat().st_uid != os.getuid()))


def diff(old, new):
    return ''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile='当前版本', tofile='保存后'))


def native_arguments(interactive=True):
    """A first-value policy file also protects OpenSSH's native ProxyJump child.

    Original Includes and Match rules are read by OpenSSH unchanged. The system
    configuration is included after the user's file, matching native precedence.
    """
    from app.main import DATA
    import secrets
    folder = DATA / 'ssh-policy'
    folder.mkdir(mode=0o700, exist_ok=True)
    lines = ['Host *', '    StrictHostKeyChecking ' + ('ask' if interactive else 'yes'),
             '    BatchMode ' + ('no' if interactive else 'yes'), '    PermitLocalCommand no',
             '    RemoteCommand none', '    ForkAfterAuthentication no',
             '    ControlMaster no', '    ControlPath none']
    if store.root() != Path.home() / '.ssh':
        lines += ['    UserKnownHostsFile ' + quote(str(store.path('known_hosts'))),
                  '    GlobalKnownHostsFile none']
    lines += ['Include ' + quote(str(store.path('config'))), 'Host *', 'Include /etc/ssh/ssh_config', '']
    content = '\n'.join(lines).encode()
    target = folder / (store.digest(content) + '.conf')
    if not target.exists():
        temp = folder / ('.write-' + secrets.token_hex(12))
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
    if store.read(target, private=True) != content:
        raise HTTPException(409, 'SSH 运行策略文件已改变，请检查宿主机配置')
    return ['-F', str(target)]


def effective(host, cancel=None):
    alias(host)
    checked_sources()
    try:
        output = run(['ssh', '-G'] + native_arguments() + ['--', host], cancel=cancel)
    except CommandFailure:
        raise HTTPException(400, 'OpenSSH 无法求值此配置，请检查 SSH 配置语法') from None
    values = {}
    for line in output.splitlines():
        key, _, value = line.partition(' ')
        values.setdefault(key, []).append(value)
    # Never return commands, tokens, arbitrary environment values or config dumps.
    allowed = ('hostname', 'user', 'port', 'identityfile', 'identityagent', 'proxyjump', 'forwardagent',
               'identitiesonly', 'stricthostkeychecking', 'userknownhostsfile', 'hostkeyalias',
               'preferredauthentications', 'pubkeyauthentication', 'passwordauthentication',
               'kbdinteractiveauthentication')
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
        if existing:
            store.remove('host-meta', existing['alias'].lower())
        store.remove('host-meta', row['alias'].lower())
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
                value = read_source(source)[1].decode()
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
                    line = ' '.join(part if part.lower().lstrip('!') in ('match', 'all', 'canonical', 'final', 'host', 'originalhost', 'user', 'localuser', 'localnetwork', 'exec', 'tagged', 'command') else quote(part) for part in parts)
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
