"""Authenticated SSH management API. Secret operations are purpose-bound."""
import ipaddress
import json
from pathlib import Path
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from app import access, passwords
from app.ssh import configuration as config, hosts, jobs, keys, storage as store, terminals

router = APIRouter(prefix='/api/ssh', tags=['ssh'], dependencies=[Depends(access.admin)])


def audit(target, action):
    from app.main import audit as record
    record('ssh', target, action)


def secure(request):
    if request.url.scheme == 'https':
        return
    try:
        local = ipaddress.ip_address(request.client.host).is_loopback
    except (ValueError, AttributeError):
        local = False
    if local and request.url.hostname in ('localhost', '127.0.0.1', '::1'):
        return
    raise HTTPException(403, 'SSH 口令与私钥操作需要 HTTPS。请使用配置了证书的 HTTPS 入口，或在宿主机 localhost 操作')


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


def require_grant(request, value, operation, target):
    secure(request)
    token = value.get('grant', '')
    with store.mutex:
        row = store.get('grant', store.digest(str(token).encode()))
        if row:
            store.remove('grant', row['id'])
    session = store.digest(request.cookies.get('orh', '').encode())
    if not row or row['expires'] < time.time() or row['session'] != session or row['operation'] != operation or row['target'] != target:
        raise HTTPException(403, '请重新验证管理员密码')
    # One-use, and delete before any sensitive file is opened.


@router.get('/overview')
def overview(request: Request):
    data = config.inventory()
    try:
        secure(request)
        protected = True
    except HTTPException:
        protected = False
    return dict(data, directory=str(store.root()), secure_transport=protected, sessions=terminals.sessions())


@router.post('/reauth')
def reauth(request: Request, value=Depends(body)):
    secure(request)
    from app import main
    main.throttle(request)
    operation = value.get('operation')
    target = str(value.get('target', ''))
    if operation not in ('key-import', 'key-export', 'key-delete', 'key-passphrase', 'config-read',
                         'config-apply', 'config-trust', 'backup-restore', 'host-update', 'host-remove') or len(target) > 100:
        raise HTTPException(400, '管理员复验操作无效')
    if not passwords.verify(str(value.get('password', ''))):
        audit('administrator', 'reauth-failed')
        raise HTTPException(403, '管理员密码错误')
    token = secrets.token_urlsafe(32)
    store.put('grant', store.digest(token.encode()), dict(operation=operation, target=target, expires=time.time() + 120,
              session=store.digest(request.cookies.get('orh', '').encode())))
    return dict(grant=token)


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
    store.put('host-meta', host.lower(), dict(group=str(value.get('group', ''))[:80], favorite=bool(value.get('favorite'))))
    audit(host, 'connection-organize')
    return dict(ok=True)


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
    scan = store.get('scan', value.get('scan_id'))
    if scan and hosts.known(scan['host'])['entries']:
        require_grant(request, value, 'host-update', scan['host'])
    result = hosts.trust(value)
    audit('known_hosts', 'fingerprint-trust')
    return result


@router.post('/hosts/{host}/remove')
def remove_host(host: str, request: Request, value=Depends(body)):
    require_grant(request, value, 'host-remove', host)
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
    require_grant(request, value, 'key-import', name)
    result = keys.import_key(value)
    audit(name, 'key-import')
    return result


@router.post('/keys/{name}/export')
def key_export(name: str, request: Request, value=Depends(body)):
    keys.key_name(name)
    require_grant(request, value, 'key-export', name)
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
    require_grant(request, value, 'key-passphrase', name)
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
    require_grant(request, value, 'key-delete', name)
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
    content = store.read(Path(file['path'])).decode()
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
        old = store.read(Path(file['path'])).decode()
        if store.digest(old.encode()) != value.get('revision'):
            raise HTTPException(409, '配置已修改，请重新打开')
        # Syntax and effective rules are checked by OpenSSH at use time. Validation
        # here deliberately avoids executing an unapproved Match exec command.
        for line in text.splitlines():
            config.tokens(line)
        result = dict(file=file['relative'], text=text, revision=value['revision'], diff=config.diff(old, text))
    config.validate(result['file'], result['text'])
    token = secrets.token_hex(16)
    store.put('plan', token, dict(result, expires=time.time() + 300))
    return dict(result, plan=token)


@router.post('/config/apply')
def config_apply(request: Request, value=Depends(body)):
    plan = store.get('plan', value.get('plan'))
    if not plan or plan['expires'] < time.time():
        raise HTTPException(409, '配置预览已过期，请重新预览')
    require_grant(request, value, 'config-apply', plan['file'])
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


@router.post('/config/trust')
def config_trust(request: Request, value=Depends(body)):
    result = config.discover()
    require_grant(request, value, 'config-trust', result['signature'])
    if value.get('signature') != result['signature'] or value.get('confirm') != result['signature']:
        raise HTTPException(409, '配置版本改变，请重新核验')
    store.put('trust-config', result['signature'], dict(created=time.time()))
    audit('config', 'native-command-rules-authorized')
    return dict(ok=True)


@router.post('/backups/restore')
def restore_backup(request: Request, value=Depends(body)):
    item = store.get('backup', value.get('backup'))
    if not item:
        raise HTTPException(404, '备份不存在')
    require_grant(request, value, 'backup-restore', item['file'])
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
