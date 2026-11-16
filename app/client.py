"""Device selection for the local Client, reusing Cloud and Mesh authority."""
import json
import os
import time

from urllib.parse import urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request

from app import cloud_agent, discovery
from app.remote_connect import tailscale
from app.remote_connect.api import RemoteRoute, administrator, body, console_connection, peer_desktop

router = APIRouter(prefix='/api/client', tags=['client'], route_class=RemoteRoute,
                   dependencies=[Depends(administrator)])


def device_model(device, mesh, local_id):
    identifier = device['instance_id']
    local = identifier == local_id
    published = device.get('mesh') or {}
    addresses = published.get('ips') or []
    peer = next((peer for peer in mesh.get('peers', [])
                 if set(addresses).intersection(peer.get('addresses', []))), {})
    services = published.get('services') or []
    return dict(device_id=identifier, name=device['name'], os=device.get('os', ''),
                local=local, heartbeat_online=device.get('online', False),
                last_seen=device.get('last_seen'), mesh_ips=addresses,
                mesh_state=mesh.get('state', ''), path='local' if local else peer.get('route', 'idle'),
                agent_published=local or 8765 in services,
                desktop_published=21118 in services,
                web_urls=device.get('manual_addresses', []) + device.get('addresses', []),
                capabilities=dict(agent=local or 8765 in services, desktop=21118 in services))


def account_directory():
    from app.main import DATA
    cache=DATA/'device-directory.json'
    fingerprint=cloud_agent.fingerprint()
    try:
        directory=cloud_agent.directory(strict=True)
    except HTTPException as error:
        if error.status_code not in (502,503,504):
            raise
        stored=json.loads(cache.read_text()) if cache.exists() else {}
        return stored.get('devices',[]) if stored.get('account')==fingerprint else [],str(error.detail),stored.get('updated')
    value=dict(account=fingerprint,devices=directory,updated=time.time())
    temporary=cache.with_suffix('.tmp')
    with cloud_agent.lock:
        descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(descriptor,'w') as output:json.dump(value,output)
        temporary.replace(cache)
    return directory,'',value['updated']


@router.get('/devices')
def devices():
    identity = discovery.identity()
    mesh = tailscale.status()
    error = ''
    directory = []
    if cloud_agent.binding():
        try:
            directory, error, _ = account_directory()
        except HTTPException as failure:
            error = failure.detail
    if not any(device['instance_id'] == identity['instance_id'] for device in directory):
        from app.main import host
        directory.insert(0, dict(instance_id=identity['instance_id'], name=identity['name'],
                                 os=host.info()['system'], online=False))
    return dict(devices=[device_model(device, mesh, identity['instance_id']) for device in directory if device.get('kind')!='controller-only'],
                cloud=dict(bound=bool(cloud_agent.binding()), error=error),
                mesh=dict(state=mesh.get('state', ''), error=mesh.get('error', '')))


def target(device_id):
    directory, error, _ = account_directory()
    device = next((device for device in directory
                   if device['instance_id'] == device_id), None)
    if not device:
        raise HTTPException(404, '设备已解绑或不属于当前账号，请刷新设备列表')
    mesh = tailscale.status()
    if mesh.get('state') != 'Running':
        raise HTTPException(503, 'Mesh 尚未连接，请在诊断中检查组网状态')
    addresses = (device.get('mesh') or {}).get('ips') or []
    address = next((ip for ip in addresses if ':' not in ip), next(iter(addresses), None))
    if not address:
        raise HTTPException(409, '目标尚未接入 Mesh，请检查目标后台服务')
    return device, mesh, address, bool(error)


@router.post('/connect')
def connect(request: Request, value=Depends(body)):
    device_id = value.get('device_id')
    if not isinstance(device_id, str) or not device_id:
        raise HTTPException(400, '请选择设备')
    local = discovery.identity()
    context = dict(client=str(request.base_url).rstrip('/') + '/client', device_id=device_id)
    if device_id == local['instance_id']:
        context['device_name'] = local['name']
        return dict(device_id=device_id, path='local', url='/?' + urlencode(context) + '#overview')
    device, mesh, address, offline = target(device_id)
    if 8765 not in ((device.get('mesh') or {}).get('services') or []):
        raise HTTPException(409, '目标未发布 Agent 管理能力')
    # The existing endpoint verifies the remote instance ID through Mesh before
    # creating the target-specific, single-use account Ticket.
    result = (tailscale.request('/console',dict(peer_ip=address,device_id=device_id),timeout=30) if offline
              else console_connection(dict(peer_ip=address, device_id=device_id), require_ticket=True))
    parts = urlsplit(result['url'])
    if not parts.fragment and not offline:
        raise HTTPException(401, '账号会话已过期，请在本机重新登录 ORH 后连接')
    peer = next((peer for peer in mesh.get('peers', []) if address in peer['addresses']), {})
    context.update(device_name=device['name'], peer_ip=next(iter((mesh.get('device') or {}).get('addresses') or []), ''))
    url = urlunsplit((parts.scheme, parts.netloc, '/' if offline else parts.path, urlencode(context), '' if offline else parts.fragment))
    return dict(device_id=device_id, path=peer.get('route', 'idle'), url=url)


@router.get('/link')
def link(peer_ip: str = ''):
    mesh = tailscale.status()
    peer = next((peer for peer in mesh.get('peers', []) if peer_ip in peer['addresses']), {})
    return dict(state=mesh.get('state', ''), path=peer.get('route', 'idle'), error=mesh.get('error', ''))


@router.post('/desktop')
def desktop(value=Depends(body)):
    from app import modules
    modules.require('desktop')
    device, mesh, address, _ = target(value.get('device_id'))
    if 21118 not in ((device.get('mesh') or {}).get('services') or []):
        raise HTTPException(409, '目标未发布远程桌面能力，请检查 RustDesk')
    return peer_desktop(dict(peer_ip=address))


@router.get('/mesh')
def mesh_status():
    status=tailscale.status()
    try:
        forwards=tailscale.request('/forwards')
        error=''
    except tailscale.TailscaleError as failure:
        forwards=[];error=str(failure)
    return dict(status=status,forwards=forwards,error=error)


@router.post('/mesh/ping')
def mesh_ping(value=Depends(body)):
    from app.remote_connect.api import peer_address
    return tailscale.request('/ping',{'peer_ip':peer_address(value)},timeout=30)


@router.post('/mesh/netcheck')
def mesh_netcheck():
    return tailscale.request('/netcheck',{},timeout=30)


@router.post('/mesh/control')
def mesh_control(value=Depends(body)):
    action=value.get('action')
    if action not in ('connect','disconnect','reconnect'):raise HTTPException(400,'不支持的组网操作')
    return tailscale.request('/control',{'action':action},timeout=25)


@router.post('/mesh/forward')
def mesh_forward(value=Depends(body)):
    from app.remote_connect.api import peer_address
    remote=value.get('remote_port');local=value.get('local_port',0)
    if type(remote) is not int or not 1<=remote<=65535 or type(local) is not int or not 0<=local<=65535:
        raise HTTPException(400,'请输入有效的 TCP 端口，自动本地端口填写 0')
    return tailscale.request('/forwards',dict(peer_ip=peer_address(value),remote_port=remote,local_port=local),timeout=30)


@router.post('/mesh/close')
def mesh_close(value=Depends(body)):
    import re
    key=value.get('id')
    if not isinstance(key,str) or not re.fullmatch('[0-9a-f]{24}',key):raise HTTPException(400,'请选择有效的转发通道')
    return tailscale.request('/forwards/'+key,method='DELETE')
