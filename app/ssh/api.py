"""SSH management API authorized by the console administrator session."""
import json
from pathlib import Path
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from app import access
from app.ssh import configuration as config, hosts, jobs, keys, storage as store, terminals

router = APIRouter(prefix='/api/ssh', tags=['ssh'], dependencies=[Depends(access.admin)])


def audit(target, action):
    from app.main import audit as record
    record('ssh', target, action)


def secure(request):
    from app.ssh.transport import require_transport
    require_transport(request)


async def body(request: Request):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 256 * 1024:
            raise HTTPException(413, 'SSH 请求内容过大')
    try:
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError):
        raise HTTPException(400, '请输入有效的 SSH 操作数据') from None


@router.get('/overview')
def overview(request: Request):
    data = config.inventory()
    try:
        secure(request)
        protected = True
    except HTTPException:
        protected = False
    return dict(data, directory=str(store.root()), secure_transport=request.url.scheme == 'https', transport_allowed=protected, sessions=terminals.sessions())


@router.post('/connections/save')
def connection_save(value=Depends(body)):
    result = config.save_connection(value)
    audit(result['alias'], 'connection-save')
    return result


@router.post('/connections/delete')
def connection_delete(value=Depends(body)):
    host = config.alias(value.get('alias'))
    if value.get('confirm') != host:
        raise HTTPException(400, '请确认删除的连接')
    result = config.delete_connection(host, value.get('managed_revision'), value.get('connection_revision'))
    audit(host, 'connection-delete')
    return result


@router.post('/connections/metadata')
def metadata(value=Depends(body)):
    host = config.alias(value.get('alias'))
    if not any(r['alias'].lower() == host.lower() for r in config.inventory()['connections']):
        raise HTTPException(404, 'SSH 连接不存在')
    with store.locked():
        managed = store.get('connection', host.lower())
        values = dict(group=str(value.get('group', '')).strip()[:80], favorite=bool(value.get('favorite')))
        revision = None
        if managed:
            managed.update(values)
            content = {k: v for k, v in managed.items() if k not in ('id', 'revision')}
            revision = store.digest(json.dumps(content, sort_keys=True).encode())
            managed['revision'] = revision
            store.put('connection', host.lower(), managed)
            store.remove('host-meta', host.lower())
        else:
            store.put('host-meta', host.lower(), values)
    audit(host, 'connection-organize')
    return dict(ok=True, revision=revision)


@router.get('/connections/{host}/effective')
def effective(host: str):
    terminals.connection(host)
    return config.effective(host)


@router.post('/connections/{host}/connect')
def connect(host: str, request: Request, value=Depends(body)):
    secure(request)
    return terminals.launch(host, bool(value.get('new', False)))


@router.post('/connections/{host}/deploy')
def deploy(host: str, request: Request, value=Depends(body)):
    secure(request)
    return terminals.launch(host, True, keys.key_name(value.get('key')))


@router.post('/connections/{host}/diagnose')
def diagnose(host: str, value=Depends(body)):
    result = jobs.start(host, value.get('kind', 'diagnose'))
    audit(host, 'diagnose-start')
    return result


@router.get('/jobs/{token}')
def job(token: str):
    return jobs.get(token)


@router.post('/jobs/{token}/cancel')
def cancel(token: str):
    return jobs.stop(token)


@router.get('/hosts/{host}')
def host_info(host: str):
    terminals.connection(host)
    return hosts.known(host)


@router.post('/hosts/trust')
def trust_host(request: Request, value=Depends(body)):
    secure(request)
    result = hosts.trust(value)
    audit('known_hosts', 'fingerprint-trust')
    return result


@router.post('/hosts/{host}/remove')
def remove_host(host: str, request: Request, value=Depends(body)):
    secure(request)
    if value.get('confirm') != host:
        raise HTTPException(400, '请确认移除的主机记录')
    result = hosts.remove(host, value.get('revision'))
    audit(host, 'fingerprint-remove')
    return result


@router.get('/keys')
def key_list():
    entries = keys.inventory()
    backups = [row for row in store.rows('backup') if row.get('kind') == 'key']
    return dict(keys=entries, backups=backups, revisions={row['file']: store.revision(row['file']) for row in backups})


@router.get('/keys/{name}/references')
def key_references(name: str):
    keys.key_name(name)
    return keys.references(name)


@router.post('/keys/generate')
def key_generate(request: Request, value=Depends(body)):
    secure(request)
    result = keys.generate(value)
    audit(result['name'], 'key-generate')
    return result


@router.post('/keys/import')
def key_import(request: Request, value=Depends(body)):
    name = keys.key_name(value.get('name'))
    secure(request)
    result = keys.import_key(value)
    audit(name, 'key-import')
    return result


@router.post('/keys/{name}/export')
def key_export(name: str, request: Request, value=Depends(body)):
    keys.key_name(name)
    secure(request)
    content = store.read(store.path(name), private=True)
    if not content:
        raise HTTPException(404, '私钥不存在')
    audit(name, 'key-export')
    return Response(content, media_type='application/octet-stream',
                    headers={'Content-Disposition': f'attachment; filename="{name}"', 'Cache-Control': 'no-store'})


@router.get('/keys/{name}/public')
def public_download(name: str):
    keys.key_name(name)
    content = store.read(store.path(name + '.pub'))
    keys.public_line(content.decode())
    return Response(content, media_type='text/plain', headers={'Content-Disposition': f'attachment; filename="{name}.pub"'})


@router.post('/keys/{name}/passphrase')
def passphrase(name: str, request: Request, value=Depends(body)):
    keys.key_name(name)
    secure(request)
    result = keys.change_passphrase(name, value)
    audit(name, 'key-passphrase-change')
    return result


@router.post('/keys/{name}/recover-public')
def recover_public(name: str, request: Request, value=Depends(body)):
    secure(request)
    result = keys.recover_public(name, value)
    audit(name, 'key-public-derive')
    return result


@router.post('/keys/{name}/delete')
def key_delete(name: str, request: Request, value=Depends(body)):
    keys.key_name(name)
    if value.get('confirm') != name:
        raise HTTPException(400, '请确认删除的密钥')
    secure(request)
    result = keys.delete(name, value)
    audit(name, 'key-delete')
    return result


@router.get('/config')
def config_list():
    result = config.discover()
    return dict(result, include={'linked': config.include_plan()['linked']}, backups=[r for r in store.rows('backup') if r['file'] in ('config', 'known_hosts', config.MANAGED) or any(f['relative'] == r['file'] and f['editable'] for f in result['files'])])


@router.post('/config/read')
def config_read(request: Request, value=Depends(body)):
    file_id = value.get('file')
    secure(request)
    file = next((f for f in config.discover()['files'] if f['id'] == file_id), None)
    if not file:
        raise HTTPException(404, '配置文件不存在')
    content = config.read_source(file['path'])[1].decode()
    if 'PRIVATE KEY-----' in content or '\x00' in content:
        raise HTTPException(403, '私钥只能通过专用密钥导出操作读取')
    return dict(file, text=content)


@router.post('/config/plan')
def config_plan(request: Request, value=Depends(body)):
    secure(request)
    if value.get('action') == 'include':
        result = config.include_plan()
    else:
        file = next((f for f in config.discover()['files'] if f['id'] == value.get('file') and f['editable']), None)
        if not file:
            raise HTTPException(403, '此配置不在可编辑的 SSH 管理范围')
        text = value.get('text')
        if not isinstance(text, str) or '\x00' in text or len(text.encode()) > store.LIMIT or 'PRIVATE KEY-----' in text:
            raise HTTPException(400, '配置文本无效')
        old = config.read_source(file['path'])[1].decode()
        if store.digest(old.encode()) != value.get('revision'):
            raise HTTPException(409, '配置已修改，请重新打开')
        # Syntax and effective rules are checked by OpenSSH at use time. Validation
        # here avoids executing Match exec while previewing configuration.
        for line in text.splitlines():
            config.tokens(line)
        result = dict(file=file['relative'], text=text, revision=value['revision'], diff=config.diff(old, text))
    if result.get('read_only'):
        raise HTTPException(403, '原生 Config 是外部工具管理的软链接，请在其配置源中加入受管 Include')
    config.validate(result['file'], result['text'])
    token = secrets.token_hex(16)
    store.put('plan', token, dict(result, expires=time.time() + 300))
    return dict(result, plan=token)


@router.post('/config/apply')
def config_apply(request: Request, value=Depends(body)):
    plan = store.get('plan', value.get('plan'))
    if not plan or plan['expires'] < time.time():
        raise HTTPException(409, '配置预览已过期，请重新预览')
    secure(request)
    if value.get('confirm') != plan['file']:
        raise HTTPException(400, '请确认配置文件名称')
    with store.locked():
        config.validate(plan['file'], plan['text'])
        if plan['file'] == 'config' and not store.path(config.MANAGED).exists():
            store.write(config.MANAGED, config.render(store.rows('connection')), store.digest(b''), False)
        result = store.write(plan['file'], plan['text'].encode(), plan['revision'])
        store.remove('plan', plan['id'])
    audit(plan['file'], 'config-apply')
    return result

@router.post('/backups/restore')
def restore_backup(request: Request, value=Depends(body)):
    item = store.get('backup', value.get('backup'))
    if not item:
        raise HTTPException(404, '备份不存在')
    secure(request)
    if value.get('confirm') != item['file']:
        raise HTTPException(400, '请确认恢复目标')
    from app.main import DATA
    content = store.read(DATA / 'ssh-backups' / item['id'], private=True)
    with store.locked():
        if item['file'] == config.MANAGED:
            if content != config.render(item.get('connections', [])):
                raise HTTPException(409, '此受管配置备份缺少匹配的连接元数据，恢复已停止')
            result = config.commit_connections(item['connections'], value.get('revision'))
        else:
            if item['file'] == 'config' or any(f.get('relative') == item['file'] for f in config.discover()['files']):
                config.validate(item['file'], content.decode())
            result = store.write(item['file'], content, value.get('revision'))
    audit(item['file'], 'backup-restore')
    return result
