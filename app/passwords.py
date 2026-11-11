"""Local password store. No plaintext or recoverable passwords are persisted."""
import hashlib
import hmac
import json
import os
import secrets
import threading
from fastapi import HTTPException

lock = threading.RLock()
ITERATIONS = 600_000


def path():
    from app import main
    return main.DATA / 'credentials.json'


def record():
    try:
        return json.loads(path().read_text())
    except FileNotFoundError:
        return None


def fingerprint():
    r = record()
    return hashlib.sha256(json.dumps(r, sort_keys=True).encode()).hexdigest() if r else None


def verify(password):
    r = record()
    if not r:
        return False
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(r['salt']), r['iterations']).hex()
    return hmac.compare_digest(digest, r['digest'])


def save(password, initial=False):
    salt = secrets.token_bytes(32)
    r = dict(salt=salt.hex(), iterations=ITERATIONS,
             digest=hashlib.pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS).hex())
    with lock:
        if initial:
            try:
                fd = os.open(path(), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                raise HTTPException(409, '密码已设置，请登录')
            with os.fdopen(fd, 'w') as f:
                json.dump(r, f)
        else:
            tmp = path().with_suffix('.tmp')
            fd = os.open(tmp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'w') as f:
                json.dump(r, f)
            tmp.replace(path())
