"""Private metadata, separate from metrics and user project contents."""
import json
import os
import secrets
import sqlite3
from fastapi import HTTPException


def connection():
    from app.main import DATA
    path=DATA/'workspace.sqlite3'
    c=sqlite3.connect(path,timeout=10)
    os.chmod(path,0o600)
    c.execute('CREATE TABLE IF NOT EXISTS workspace (kind TEXT, id TEXT, value TEXT, revision TEXT, PRIMARY KEY(kind,id))')
    return c


def rows(kind):
    with connection() as c:
        return [dict(json.loads(value),id=key,revision=revision) for key,value,revision in c.execute('SELECT id,value,revision FROM workspace WHERE kind=? ORDER BY rowid',(kind,))]


def get(kind,key):
    return next((x for x in rows(kind) if x['id']==key),None) or fail()


def fail():raise HTTPException(404,'记录不存在')


def save(kind,value,key=None,revision=None):
    key=key or secrets.token_hex(8)
    token=secrets.token_hex(16)
    with connection() as c:
        if revision is None:
            try:c.execute('INSERT INTO workspace VALUES (?,?,?,?)',(kind,key,json.dumps(value),token))
            except sqlite3.IntegrityError:raise HTTPException(409,'记录已存在')
        else:
            result=c.execute('UPDATE workspace SET value=?,revision=? WHERE kind=? AND id=? AND revision=?',(json.dumps(value),token,kind,key,revision))
            if not result.rowcount:raise HTTPException(409,'记录已修改，请刷新后重试')
    return dict(value,id=key,revision=token)


def remove(kind,key,revision):
    with connection() as c:
        if not c.execute('DELETE FROM workspace WHERE kind=? AND id=? AND revision=?',(kind,key,revision)).rowcount:
            raise HTTPException(409,'记录已修改，请刷新后重试')
