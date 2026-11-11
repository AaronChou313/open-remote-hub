"""Key inventory and ssh-keygen via protected PTYs."""
import base64
import contextlib
import os
from pathlib import Path
import re
import secrets
import shutil
import struct
import tempfile

from fastapi import HTTPException
from app.ssh import storage as store
from app.ssh.process import run, keygen, CommandFailure

RESERVED = {'config', 'openremotehub.conf', 'known_hosts', 'authorized_keys', 'environment', 'rc'}


def key_name(value):
    value = store.name(value)
    if value in RESERVED or value.endswith(('.pub', '.old', '.conf')):
        raise HTTPException(400, '密钥名称与 SSH 配置文件冲突')
    return value


def public_line(text):
    if not isinstance(text, str) or len(text) > 16384 or len(text.strip().splitlines()) != 1:
        raise HTTPException(400, '请输入单行 OpenSSH 公钥')
    parts = text.strip().split(None, 2)
    if len(parts) < 2 or not re.fullmatch(r'(ssh-|ecdsa-|sk-)[A-Za-z0-9@._+-]+', parts[0]):
        raise HTTPException(400, '公钥格式无效，不支持 authorized_keys 选项前缀')
    try:
        blob = base64.b64decode(parts[1], validate=True)
        length = struct.unpack('>I', blob[:4])[0]
        if blob[4:4 + length].decode() != parts[0]:
            raise ValueError()
    except (ValueError, UnicodeError, struct.error):
        raise HTTPException(400, '公钥数据无效') from None
    line = ' '.join(parts)
    try:
        fingerprint = run(['ssh-keygen', '-l', '-E', 'sha256', '-f', '-'], input_data=(line + '\n').encode())
    except CommandFailure:
        raise HTTPException(400, 'OpenSSH 无法识别此公钥') from None
    match = re.search(r'^(\d+) (SHA256:\S+).*\(([^)]+)\)', fingerprint.strip())
    if not match:
        raise HTTPException(400, '无法读取公钥指纹')
    return dict(public=line, fingerprint=match[2], type=match[3], bits=int(match[1]))


def encrypted(data):
    if b'ENCRYPTED' in data:
        return True
    if b'BEGIN OPENSSH PRIVATE KEY' in data:
        try:
            blob = base64.b64decode(b''.join(data.splitlines()[1:-1]))
            offset = len(b'openssh-key-v1\0')
            length = struct.unpack('>I', blob[offset:offset + 4])[0]
            return blob[offset + 4:offset + 4 + length] != b'none'
        except (ValueError, struct.error):
            return None
    return None


def identity_path(value, config, host):
    import getpass
    values = {'%': '%', 'd': str(Path.home()), 'h': config.get('hostname', host),
              'n': host, 'r': config.get('user', getpass.getuser()), 'p': str(config.get('port', '22')),
              'u': getpass.getuser(), 'i': str(os.getuid()), 'k': config.get('hostkeyalias', host)}
    expanded = re.sub(r'%([%dhnrpuik])', lambda match: values[match[1]], value)
    return str(Path(os.path.expandvars(os.path.expanduser(expanded))).absolute())


def references(key):
    from app.ssh.configuration import inventory, effective
    target = str(store.path(key))
    result, unresolved = [], []
    for row in store.rows('connection'):
        if row.get('identityfile') and identity_path(row['identityfile'], row, row['alias']) in (target, target + '.pub'):
            result.append(row['alias'])
    for row in inventory()['connections']:
        try:
            config = effective(row['alias'])
        except HTTPException:
            unresolved.append(row['alias'])
            continue
        for value in config.get('identityfile', []):
            expanded = identity_path(value, config, row['alias'])
            if expanded in (target, target + '.pub'):
                if row['alias'] not in result:
                    result.append(row['alias'])
                break
    return dict(connections=result, unresolved=unresolved)


def inventory():
    entries = []
    names = set()
    for path in sorted(store.root().iterdir()):
        if path.name.startswith('.') or not path.is_file() or path.is_symlink():
            continue
        if path.suffix == '.pub':
            names.add(path.name[:-4])
        elif path.name not in RESERVED:
            try:
                if b'PRIVATE KEY-----' in store.read(path, private=True)[:200]:
                    names.add(path.name)
            except HTTPException:
                continue
    for name in sorted(names):
        try:
            key_name(name)
            private = store.read(store.path(name), private=True)
            pub = store.read(store.path(name + '.pub')).decode()
            info = public_line(pub) if pub else {}
            if not pub and private:
                try:
                    fingerprint = run(['ssh-keygen', '-l', '-E', 'sha256', '-f', str(store.path(name))])
                    match = re.search(r'^(\d+) (SHA256:\S+).*\(([^)]+)\)', fingerprint.strip())
                    if match:
                        info = dict(fingerprint=match[2], type=match[3], bits=int(match[1]))
                except CommandFailure:
                    pass
            entries.append(dict(name=name, private=bool(private), encrypted=encrypted(private) if private else None,
                                revision=store.digest(private), public_revision=store.digest(pub.encode()),
                                **info))
        except HTTPException:
            entries.append(dict(name=name, unavailable=True))
    return entries


@contextlib.contextmanager
def staging():
    # Only encrypted or original private-key material is stored here, never its passphrase.
    folder = Path(tempfile.mkdtemp(prefix='.orh-key-', dir=store.root()))
    os.chmod(folder, 0o700)
    try:
        yield folder / 'key'
    finally:
        shutil.rmtree(folder)


def ensure_new(name):
    for item in (store.path(name), store.path(name + '.pub')):
        if item.exists() or item.is_symlink():
            raise HTTPException(409, '同名密钥或公钥已存在，请使用其他名称')


def publish(name, private, public):
    """Hard-link publication is exclusive, rollback removes only our own files."""
    destinations = []
    try:
        for source, target in ((private, store.path(name)), (public, store.path(name + '.pub'))):
            if source is None:
                continue
            os.chmod(source, 0o600)
            os.link(source, target, follow_symlinks=False)
            destinations.append(target)
    except OSError as error:
        for path in destinations:
            path.unlink()
        if isinstance(error, FileExistsError):
            raise HTTPException(409, '密钥文件已存在，未覆盖') from None
        raise HTTPException(400, '密钥文件保存失败，已撤回本次创建') from None


def generate(body):
    name = key_name(body.get('name'))
    comment = str(body.get('comment', '')).strip()
    if len(comment) > 200 or any(c in comment for c in '\r\n\x00'):
        raise HTTPException(400, '密钥备注无效')
    with store.locked(), staging() as temp:
        ensure_new(name)
        password = str(body.get('passphrase', ''))
        keygen(['ssh-keygen', '-q', '-t', 'ed25519', '-a', '64', '-f', str(temp), '-C', comment], [password, password])
        public = public_line(temp.with_suffix('.pub').read_text())
        publish(name, temp, temp.with_suffix('.pub'))
    return dict(name=name, **public)


def import_key(body):
    name = key_name(body.get('name'))
    private = str(body.get('private', ''))
    supplied_public = str(body.get('public', '')).strip()
    if not private and not supplied_public:
        raise HTTPException(400, '请选择私钥或公钥文件')
    if len(private.encode()) > 65536:
        raise HTTPException(413, '私钥文件过大')
    with store.locked(), staging() as temp:
        ensure_new(name)
        if private:
            if 'PRIVATE KEY-----' not in private[:200]:
                raise HTTPException(400, '请输入 OpenSSH 或 PEM 私钥')
            temp.write_text(private)
            temp.chmod(0o600)
            derived = public_line(keygen(['ssh-keygen', '-y', '-f', str(temp)], [str(body.get('passphrase', ''))]))
            if supplied_public and public_line(supplied_public)['fingerprint'] != derived['fingerprint']:
                raise HTTPException(400, '私钥与公钥不匹配')
            public = public_line(supplied_public) if supplied_public else derived
        else:
            public = public_line(supplied_public)
        pubpath = temp.with_suffix('.pub')
        pubpath.write_text(public['public'] + '\n')
        publish(name, temp if private else None, pubpath)
    return dict(name=name, **public)


def change_passphrase(name, body):
    key_name(name)
    with store.locked(), staging() as temp:
        content = store.read(store.path(name), private=True)
        if not content:
            raise HTTPException(404, '私钥不存在')
        if store.digest(content) != body.get('revision'):
            raise HTTPException(409, '私钥已修改，请刷新')
        temp.write_bytes(content)
        temp.chmod(0o600)
        new = str(body.get('passphrase', ''))
        answers = [str(body.get('old_passphrase', '')), new, new] if encrypted(content) is not False else [new, new]
        keygen(['ssh-keygen', '-p', '-f', str(temp)], answers)
        # Keep a recovery copy in the user's original encryption format.
        return store.write(name, temp.read_bytes(), body['revision'])


def delete(name, body):
    key_name(name)
    ref = references(name)
    if ref['connections'] or ref['unresolved']:
        raise HTTPException(409, '密钥仍被连接引用，或配置尚未完成核验，请先解除引用并核验配置')
    from app.ssh.terminals import sessions
    if any(row.get('key') == name and row['running'] for row in sessions()):
        raise HTTPException(409, '部署此密钥的终端仍在运行，请先退出该终端')
    with store.locked():
        private = store.read(store.path(name), private=True)
        public = store.read(store.path(name + '.pub'))
        if store.digest(private) != body.get('revision') or store.digest(public) != body.get('public_revision'):
            raise HTTPException(409, '密钥文件已改变，请刷新')
        backups = []
        for key, content in ((name, private), (name + '.pub', public)):
            if content:
                backups.append(store.backup(key, content))
                store.path(key).unlink()
        return dict(backups=backups)


def recover_public(name, body):
    key_name(name)
    with store.locked(), staging() as temp:
        private = store.read(store.path(name), private=True)
        if not private:
            raise HTTPException(404, '私钥不存在')
        if store.read(store.path(name + '.pub')):
            raise HTTPException(409, '公钥已存在，未覆盖')
        temp.write_bytes(private)
        temp.chmod(0o600)
        result = public_line(keygen(['ssh-keygen', '-y', '-f', str(temp)], [str(body.get('passphrase', ''))]))
        public = temp.with_suffix('.pub')
        public.write_text(result['public'] + '\n')
        publish(name, None, public)
        return result
