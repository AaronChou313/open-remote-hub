"""Saved Web entry points. Visiting an application uses its own HTTP service."""
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app import workspace_store as store

router = APIRouter(prefix='/api/applications', tags=['applications'])


class Application(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    mode: str = 'host'
    scheme: str = 'http'
    port: int | None = None
    path: str = Field(default='/', max_length=4096)
    url: str = Field(default='', max_length=4096)
    group: str = Field(default='', max_length=80)
    revision: str | None = None


def values(body):
    data = dict(name=body.name.strip(), mode=body.mode, group=body.group.strip())
    if not data['name']:
        raise HTTPException(400, '请输入应用名称')
    if body.mode == 'host':
        if body.scheme not in ('http', 'https') or body.port is None or not 1 <= body.port <= 65535:
            raise HTTPException(400, '请选择 HTTP / HTTPS，并输入 1–65535 的端口')
        if not body.path.startswith('/') or body.path.startswith('//') or '\\' in body.path or any(ord(c) < 32 for c in body.path):
            raise HTTPException(400, '应用路径以单个 / 开头')
        data.update(scheme=body.scheme, port=body.port, path=body.path)
    elif body.mode == 'custom':
        try:
            parsed = urlsplit(body.url)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or any(c.isspace() for c in body.url):
                raise ValueError()
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                raise ValueError()
        except ValueError:
            raise HTTPException(400, '请输入完整的 HTTP / HTTPS 访问地址') from None
        data['url'] = body.url
    else:
        raise HTTPException(400, '请选择当前主机或自定义地址')
    return data


def audit(key, action):
    from app.main import audit as record
    record('application', key, action)


@router.get('')
def applications():
    return dict(applications=sorted(store.rows('application'), key=lambda value:value['name'].casefold()))


@router.post('')
def create(body: Application):
    result = store.save('application', values(body))
    audit(result['id'], 'add')
    return result


@router.post('/{key}')
def update(key: str, body: Application):
    if not body.revision:
        raise HTTPException(409, '请重新打开应用设置')
    result = store.save('application', values(body), key, body.revision)
    audit(key, 'edit')
    return result


class Remove(BaseModel):
    revision: str


@router.post('/{key}/remove')
def remove(key: str, body: Remove):
    store.remove('application', key, body.revision)
    audit(key, 'remove')
    return dict(ok=True)
