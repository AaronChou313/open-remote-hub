from contextlib import contextmanager
"""Durable, revocable browser sessions. Only digests are persisted."""
import hashlib
import sqlite3
import time
from fastapi import Request, HTTPException


@contextmanager
def connection():
    from app import main
    c=sqlite3.connect(main.DATA/'auth.sqlite3',timeout=10)
    c.execute('CREATE TABLE IF NOT EXISTS sessions (digest TEXT PRIMARY KEY, role TEXT, expires REAL, credential TEXT)')
    try:
        with c:
            yield c
    finally:
        c.close()


def credential(role):
    from app import passwords, cloud_agent
    return cloud_agent.fingerprint() or passwords.fingerprint() or 'unconfigured'


def create(token,role,expires):
    with connection() as c:
        c.execute('DELETE FROM sessions WHERE expires < ?',(time.time(),))
        c.execute('INSERT INTO sessions VALUES (?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),role,expires,credential(role)))


def get(token):
    if not token or credential('admin') == 'unconfigured':return None
    with connection() as c:
        row=c.execute('SELECT role,expires,credential FROM sessions WHERE digest=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if row and row[1]>time.time() and row[2]==credential(row[0]):return dict(role=row[0],expires=row[1])
    return None


def revoke(token):
    with connection() as c:c.execute('DELETE FROM sessions WHERE digest=?',(hashlib.sha256(token.encode()).hexdigest(),))


def admin(request:Request):
    session=get(request.cookies.get('orh',''))
    if not session or session['role']!='admin':raise HTTPException(403,'仅管理员可操作终端')
    return session


def revoke_all():
    with connection() as c:
        c.execute('DELETE FROM sessions')
