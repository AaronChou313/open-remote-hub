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


def call(base, path, body, credential=None):
    headers = {'Authorization':'Bearer '+credential} if credential else {}
    try:
        with httpx.Client(timeout=12,trust_env=False) as client:
            response = client.post(base+path,json=body,headers=headers)
    except httpx.HTTPError:
        raise HTTPException(503,'暂时无法连接 Cloud，请稍后重试') from None
    if response.status_code >= 400:
        detail = response.json().get('detail','Cloud 请求失败') if response.headers.get('content-type','').startswith('application/json') else 'Cloud 请求失败'
        raise HTTPException(response.status_code, detail)
    return response.json()


def local_address(address):
    networks = ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','100.64.0.0/10')
    return address.version == 4 and any(address in ipaddress.ip_network(network) for network in networks)


def metadata():
    from app import main
    value = discovery.identity()
    hosts = set(main.NETWORK.hosts) - {'localhost','127.0.0.1','::1'}
    if main.NETWORK.bind not in ('127.0.0.1','::1','localhost'):
        stats = psutil.net_if_stats()
        for name, items in psutil.net_if_addrs().items():
            if name not in stats or not stats[name].isup or name.startswith(('bridge','veth','docker','br-','vmenet','utun')):
                continue
            for item in items:
                try:
                    address = ipaddress.ip_address(item.address)
                    if local_address(address):
                        hosts.add(str(address))
                except ValueError:
                    continue
        from app.remote_connect import tailscale
        try:
            tail = tailscale.json_command(['status','--json']).get('Self',{})
            hosts.update(ip for ip in tail.get('TailscaleIPs',[]) if ':' not in ip)
            if tail.get('DNSName'):
                hosts.add(tail['DNSName'].rstrip('.'))
        except tailscale.TailscaleError:
            pass
        main.NETWORK = replace(main.NETWORK, hosts=frozenset(set(main.NETWORK.hosts) | hosts))
        scheme = 'https' if os.environ.get('ORH_TLS_CERT_FILE') else 'http'
        urls = [f'{scheme}://{f"[{host}]" if ":" in host else host}:{main.PORT}' for host in sorted(hosts)]
    else:
        urls = []
    return dict(instance_id=value['instance_id'],name=value['name'],os=platform.system()+' '+platform.release(),
                addresses=urls,port=main.PORT)


def begin_binding(base):
    if binding():
        raise ValueError('设备已经绑定，请先在 Cloud 设备列表中解绑')
    base = cloud_url(base)
    result = call(base,'/agent/bindings/start',metadata())
    save(dict(status='pending',cloud_url=base,device_code=result['device_code'],
              user_code=result['user_code'],verification_url=result['verification_url'],expires=time.time()+result['expires_in']))
    return {key:result[key] for key in ('user_code','verification_url','expires_in')}


def synchronize():
    global last_heartbeat, last_error
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
        last_heartbeat = time.time()
        last_error = ''


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
                username=value.get('username'),last_heartbeat=last_heartbeat,error=last_error,
                pending={key:value[key] for key in ('user_code','verification_url','expires')} if value.get('status')=='pending' else None)


@router.get('/api/cloud/status')
def api_status():
    return status()


@router.post('/api/cloud/bind')
async def bind_api(request: Request):
    body = await request.json()
    try:
        return await asyncio.to_thread(begin_binding,body.get('cloud_url') or os.environ.get('ORH_CLOUD_URL',''))
    except ValueError as error:
        raise HTTPException(409,str(error)) from None


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
