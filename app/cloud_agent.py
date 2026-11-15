"""Account binding, outbound heartbeat and one-use Cloud login exchange."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import secrets
import threading
import time
from urllib.parse import urlencode, urlsplit

import httpx
import psutil
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from app import discovery

lock = threading.RLock()
last_heartbeat = 0
last_error = ''
mesh_error = ''


def state_path():
    from app.main import DATA
    return DATA / 'cloud-binding.json'


def state():
    try:
        return json.loads(state_path().read_text())
    except FileNotFoundError:
        return {}


def save(value):
    with lock:
        previous = state()
        if previous != value and ('bound' in (previous.get('status'),value.get('status'))):
            from app import access
            access.revoke_all()
        path = state_path()
        temporary = path.with_suffix('.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump(value, output)
        temporary.replace(path)


def binding():
    value = state()
    return value if value.get('status') == 'bound' else None


def fingerprint():
    value = binding()
    if not value:
        return None
    raw = json.dumps([value['cloud_url'],value['owner_id'],value['credential']], separators=(',',':'))
    return 'cloud:' + hashlib.sha256(raw.encode()).hexdigest()


def cloud_url(value):
    parsed = urlsplit(value.rstrip('/'))
    if not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError('Cloud 地址需为完整服务 Origin')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost','127.0.0.1','::1','testserver')):
        raise ValueError('公网 Cloud 服务需要 HTTPS')
    return value.rstrip('/')


def http_client(timeout=12):
    """Cloud client; honours an explicit proxy so a TUN is not required."""
    proxy = (os.environ.get('ORH_CLOUD_PROXY') or os.environ.get('HTTPS_PROXY')
             or os.environ.get('https_proxy') or '')
    return httpx.Client(timeout=timeout, trust_env=bool(proxy), proxy=proxy or None)


def call(base, path, body, credential=None):
    headers = {'Authorization':'Bearer '+credential} if credential else {}
    try:
        with http_client(12) as client:
            response = client.post(base+path,json=body,headers=headers)
    except httpx.HTTPError as error:
        try:
            import socket as _socket
            from urllib.parse import urlsplit as _urlsplit
            host=_urlsplit(base).hostname
            addrs=sorted({item[4][0] for item in _socket.getaddrinfo(host,443,type=_socket.SOCK_STREAM)})
        except OSError:
            addrs=[]
        import ssl as _ssl
        print('[cloud] 连接失败: '+repr(error)+' 地址='+','.join(addrs)+' '+_ssl.OPENSSL_VERSION, flush=True)
        raise HTTPException(503,'暂时无法连接 Cloud，请稍后重试') from None
    if response.status_code >= 400:
        detail = response.json().get('detail','Cloud 请求失败') if response.headers.get('content-type','').startswith('application/json') else 'Cloud 请求失败'
        raise HTTPException(response.status_code, detail)
    return response.json()


def directory():
    """Cloud device directory for this account, or [] when unavailable."""
    value = binding()
    if not value:
        return []
    try:
        with http_client(8) as client:
            response = client.get(value['cloud_url'] + '/agent/directory',
                                  headers={'Authorization': 'Bearer ' + value['credential']})
        return response.json() if response.status_code == 200 else []
    except (httpx.HTTPError, ValueError):
        return []


def local_address(address):
    networks = ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','100.64.0.0/10')
    return address.version == 4 and any(address in ipaddress.ip_network(network) for network in networks)


def metadata():
    from app import main
    from app.network import Network
    value = discovery.identity()
    hosts = set(Network.load().hosts) - {'localhost','127.0.0.1','::1'}
    from app.remote_connect import tailscale
    # The mesh address is the Host a peer's console forward carries, even when
    # this console only listens on loopback and is reached through the mesh.
    try:
        tail = tailscale.json_command(['status','--json']).get('Self',{})
        hosts.update(ip for ip in tail.get('TailscaleIPs',[]) if ':' not in ip)
        if tail.get('DNSName'):
            hosts.add(tail['DNSName'].rstrip('.'))
    except tailscale.TailscaleError:
        pass
    if main.NETWORK.bind not in ('127.0.0.1','::1','localhost'):
        stats = psutil.net_if_stats()
        for name, items in psutil.net_if_addrs().items():
            if name not in stats or not stats[name].isup:
                continue
            lowered = name.lower()
            if lowered.startswith(('bridge', 'veth', 'docker', 'br-', 'vmenet', 'utun',
                                   'vethernet', 'loopback', 'teredo', 'isatap', 'bluetooth')):
                continue
            for item in items:
                try:
                    address = ipaddress.ip_address(item.address)
                    if local_address(address):
                        hosts.add(str(address))
                except ValueError:
                    continue
        scheme = 'https' if os.environ.get('ORH_TLS_CERT_FILE') else 'http'
        urls = [f'{scheme}://{f"[{host}]" if ":" in host else host}:{main.PORT}' for host in sorted(hosts)]
        urls.extend([f'{scheme}://localhost:{main.PORT}',main.NETWORK.local_url(main.PORT)])
    else:
        urls = [main.NETWORK.local_url(main.PORT)]
    main.NETWORK = replace(main.NETWORK, hosts=frozenset(set(main.NETWORK.hosts) | hosts))
    return dict(instance_id=value['instance_id'],name=value['name'],os=platform.system()+' '+platform.release(),
                addresses=urls,port=main.PORT)


def enroll(base, username, password):
    """Log in with the Cloud account and register this device in one step."""
    if binding():
        raise ValueError('设备已经绑定，请先在 Cloud 设备目录解绑')
    base = cloud_url(base)
    if not username or not password:
        raise ValueError('请输入 Cloud 账号与密码')
    login = call(base,'/api/login',{'username':username,'password':password})
    account = login.get('token')
    user = login.get('user') or {}
    if not account or not user.get('id'):
        raise ValueError('Cloud 登录响应无效')
    result = call(base,'/api/devices/enroll',metadata(),account)
    save(dict(status='bound',cloud_url=base,credential=result['device_token'],
              owner_id=user['id'],username=user.get('username'),instance_id=result['instance_id'],
              portal_url=base,account_token=account,token_expires=login.get('expires',0)))
    return dict(instance_id=result['instance_id'],username=user.get('username'),cloud_url=base)


def ticket(device_id,address):
    """Short-lived console ticket for another device, using the account session."""
    value=binding()
    token=value.get('account_token') if value else None
    if not value or not token or float(value.get('token_expires') or 0)<=time.time():
        return None
    try:
        return call(value['cloud_url'],f'/api/devices/{device_id}/ticket',
                    {'address':address,'state':''},token).get('url')
    except (HTTPException,ValueError,OSError):
        return None


def synchronize():
    global last_heartbeat, last_error, mesh_error
    value = state()
    if value.get('status') == 'pending':
        if value['expires'] < time.time():
            last_error = '绑定码已过期，请生成新绑定码'
            return
        result = call(value['cloud_url'],'/agent/bindings/poll',{'device_code':value['device_code']})
        if result['status'] != 'approved':
            return
        with lock:
            if state() != value:
                return
            value = dict(status='bound',cloud_url=value['cloud_url'],credential=value['device_code'],
                         owner_id=result['owner_id'],username=result['username'],instance_id=result['instance_id'],
                         portal_url=value['verification_url'].split('#',1)[0])
            save(value)
    if value.get('status') == 'bound':
        try:
            result = call(value['cloud_url'],'/agent/heartbeat',metadata(),value['credential'])
        except HTTPException as error:
            if error.status_code == 401:
                with lock:
                    if state() == value:
                        save(dict(status='revoked',cloud_url=value['cloud_url']))
            raise
        if result['owner_id'] != value['owner_id']:
            raise HTTPException(403,'Cloud 绑定账号不匹配')
        from app import main
        synced_hosts = {urlsplit(address).hostname for address in result.get('addresses',[]) if urlsplit(address).hostname}
        main.NETWORK = replace(main.NETWORK,hosts=frozenset(set(main.NETWORK.hosts) | synced_hosts))
        last_heartbeat = time.time()
        last_error = ''
        from app.remote_connect import tailscale
        try:
            tailscale.request('/cloud/adopt',dict(base_url=value['cloud_url'],device_id=value['instance_id'],device_token=value['credential'],console_port=main.PORT,gateway_port=int(os.environ.get('ORH_DSH_GATEWAY_PORT','8767'))))
            mesh_error = ''
        except tailscale.TailscaleError as error:
            mesh_error = str(error)


def watch(stop):
    deadline = 0
    while not stop.is_set():
        value = state()
        if value.get('status') in ('pending','bound') and time.monotonic() >= deadline:
            try:
                synchronize()
            except (HTTPException, ValueError, OSError):
                global last_error
                last_error = 'Cloud 同步未成功，正在等待重试'
            deadline = time.monotonic() + (3 if value.get('status') == 'pending' else 30)
        stop.wait(1)


@asynccontextmanager
async def lifecycle(app):
    stop = threading.Event()
    worker = threading.Thread(target=watch,args=(stop,),daemon=True)
    worker.start()
    yield
    stop.set()
    await asyncio.to_thread(worker.join,15)


router = APIRouter(lifespan=lifecycle)


def status():
    value = state()
    return dict(bound=value.get('status')=='bound',cloud_url=value.get('cloud_url') or os.environ.get('ORH_CLOUD_URL'),
                username=value.get('username'),last_heartbeat=last_heartbeat,error=last_error,mesh_error=mesh_error,
                pending={key:value[key] for key in ('user_code','verification_url','expires')} if value.get('status')=='pending' else None)


@router.get('/api/cloud/status')
def api_status():
    return status()


@router.post('/api/cloud/login')
async def login_api(request: Request):
    body = await request.json()
    try:
        return await asyncio.to_thread(enroll, body.get('cloud_url') or os.environ.get('ORH_CLOUD_URL',''),
                                       str(body.get('username') or ''), str(body.get('password') or ''))
    except ValueError as error:
        raise HTTPException(409,str(error)) from None


@router.get('/auth/cloud/enter')
def enter_console(request: Request):
    from app import access
    session = access.get(request.cookies.get('orh',''))
    if not binding() or (session and session['role']=='admin'):
        return RedirectResponse('/',status_code=303)
    return login_start(request)


@router.get('/auth/cloud/start')
def login_start(request: Request):
    value = binding()
    if not value:
        raise HTTPException(409,'设备尚未绑定 Cloud')
    nonce = secrets.token_urlsafe(24)
    payload = dict(device=value['instance_id'],address=str(request.base_url).rstrip('/'),state=nonce)
    import urllib.parse
    # The Cloud's same UI is also served at its own origin.
    response = RedirectResponse(value.get('portal_url',discovery.PORTAL).rstrip('/')+'/#authorize='+urllib.parse.quote(json.dumps(payload),safe=''))
    response.set_cookie('orh_cloud_state',nonce,httponly=True,samesite='lax',secure=request.url.scheme=='https',max_age=600)
    return response


@router.get('/auth/cloud')
def callback_page():
    from app.main import ROOT
    return FileResponse(ROOT/'static/cloud-auth.html')


@router.post('/auth/cloud/exchange')
async def exchange(request: Request):
    from app import main
    value = binding()
    if not value:
        raise HTTPException(409,'设备尚未绑定 Cloud')
    body = await request.json()
    ticket = body.get('ticket','')
    if not isinstance(ticket,str) or len(ticket) > 256 or len(ticket) < 20:
        raise HTTPException(400,'登录凭据无效')
    client_state = body.get('state','')
    if client_state and not secrets.compare_digest(client_state,request.cookies.get('orh_cloud_state','')):
        raise HTTPException(403,'登录请求已失效，请重新从本机入口发起登录')
    result = await asyncio.to_thread(call,value['cloud_url'],'/agent/tickets/redeem',{'ticket':ticket},value['credential'])
    if result['instance_id'] != value['instance_id'] or result['owner_id'] != value['owner_id'] or result['state'] != client_state:
        raise HTTPException(403,'Cloud 登录目标或账号不匹配')
    if binding() != value:
        raise HTTPException(409,'设备绑定已变化，请重新登录')
    response = main.login_response(request,expires=result['expires'])
    response.delete_cookie('orh_cloud_state')
    return response
