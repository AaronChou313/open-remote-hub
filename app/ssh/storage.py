"""Scoped, locked, revision-checked files and private SQLite metadata."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import threading
import time

from fastapi import HTTPException

mutex = threading.RLock()
local_lock = threading.local()
LIMIT = 1024 * 1024


def root():
    path = Path(os.environ.get('ORH_SSH_DIR', str(Path.home() / '.ssh'))).expanduser()
    if not path.is_absolute():
        raise HTTPException(503, 'SSH 管理目录必须是绝对路径')
    if not path.exists():
        path.mkdir(mode=0o700, parents=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise HTTPException(403, 'SSH 目录必须归当前用户所有，且其他用户不可写入')
    return path


def name(value):
    import re
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', value):
        raise HTTPException(400, '文件名只允许字母、数字、点、横线和下划线')
    return value


def digest(data):
    return hashlib.sha256(data).hexdigest()


def connect():
    from app.main import DATA
    path = DATA / 'ssh.sqlite3'
    db = sqlite3.connect(path, timeout=15)
    os.chmod(path, 0o600)
    db.execute('CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, value TEXT, PRIMARY KEY(kind,id))')
    return db


def rows(kind):
    with connect() as db:
        return [dict(json.loads(value), id=key) for key, value in db.execute(
            'SELECT id,value FROM records WHERE kind=? ORDER BY rowid', (kind,))]


def get(kind, key):
    return next((row for row in rows(kind) if row['id'] == key), None)


def put(kind, key, value):
    value = {k: v for k, v in value.items() if k != 'id'}
    with connect() as db:
        db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?)', (kind, key, json.dumps(value)))
    return dict(value, id=key)


def remove(kind, key):
    with connect() as db:
        db.execute('DELETE FROM records WHERE kind=? AND id=?', (kind, key))


def open_directory(path):
    descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in Path(path).absolute().parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except OSError:
        os.close(descriptor)
        raise HTTPException(403, 'SSH 目录路径含软链接或不可访问') from None


@contextlib.contextmanager
def locked():
    with mutex:
        if getattr(local_lock, 'held', False):
            yield
            return
        directory = open_directory(root())
        try:
            fd = os.open('.openremotehub.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                info = os.fstat(fd)
                if info.st_uid != os.getuid() or info.st_nlink != 1:
                    raise HTTPException(403, 'SSH 锁文件不安全')
                fcntl.flock(fd, fcntl.LOCK_EX)
                local_lock.held = True
                try:
                    yield
                finally:
                    local_lock.held = False
            finally:
                os.close(fd)
        finally:
            os.close(directory)


def read(path, private=False):
    """Reject links in every path component, foreign ownership and hard links."""
    path = Path(path).absolute()
    descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = new
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=descriptor)
        except FileNotFoundError:
            return b''
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise HTTPException(403, 'SSH 文件的类型、所有者或链接不安全')
            if info.st_mode & (0o077 if private else 0o022):
                raise HTTPException(403, 'SSH 文件权限过宽，请通过主机文件权限设置修正')
            if info.st_size > LIMIT:
                raise HTTPException(413, 'SSH 文件超过 1 MiB 管理上限')
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                data = stream.read(LIMIT + 1)
            if len(data) > LIMIT:
                raise HTTPException(413, 'SSH 文件过大')
            return data
        finally:
            os.close(fd)
    except OSError:
        raise HTTPException(403, 'SSH 文件路径含软链接或不可访问') from None
    finally:
        os.close(descriptor)


def path(key):
    if not isinstance(key, str) or not key or len(key) > 512 or any(c in key for c in '\x00\r\n'):
        raise HTTPException(400, 'SSH 文件路径无效')
    relative = Path(key)
    if relative.is_absolute() or any(part in ('.', '..') for part in relative.parts):
        raise HTTPException(403, 'SSH 文件必须位于管理目录内')
    return root() / relative


def revision(key):
    return digest(read(path(key)))


def backup(key, data):
    """Backups are private, scoped and never contain plaintext passphrases."""
    from app.main import DATA
    folder = DATA / 'ssh-backups'
    folder.mkdir(mode=0o700, exist_ok=True)
    token = secrets.token_hex(16)
    target = folder / token
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    kind = 'key' if b'PRIVATE KEY-----' in data[:200] or key.endswith('.pub') else 'config'
    metadata = {'connections': rows('connection')} if key == 'openremotehub.conf' else {}
    put('backup', token, dict(file=key, created=time.time(), revision=digest(data), kind=kind, **metadata))
    return token


def write(key, data, expected, save_backup=True):
    """Caller holds locked(). Final rename is relative to a no-follow directory."""
    target = path(key)
    old = read(target)
    if digest(old) != expected:
        raise HTTPException(409, '文件已被其他操作修改，请刷新差异后重试')
    saved = backup(key, old) if save_backup and old else None
    directory = open_directory(target.parent)
    temp = '.orh-' + secrets.token_hex(16)
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if digest(read(target)) != expected:
            raise HTTPException(409, '文件已改变，操作已取消')
        os.rename(temp, target.name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp, dir_fd=directory)
        os.close(directory)
    return dict(revision=digest(data), backup=saved)
