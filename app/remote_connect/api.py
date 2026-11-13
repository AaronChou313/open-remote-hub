"""Remote access management under the existing console security middleware."""
import asyncio
from contextlib import asynccontextmanager
import json
import sys
import threading
import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.routing import APIRoute
from .rustdesk import client
from .rustdesk.ipc import NativeError, native
from . import tailscale, nodebaby


class RemoteRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def guarded(request):
            try:
                return await handler(request)
            except ValueError as error:
                raise HTTPException(409 if '其他窗口' in str(error) else 400, str(error)) from None
            except (NativeError, tailscale.TailscaleError, nodebaby.NodeBabyError) as error:
                raise HTTPException(503, str(error)) from None
        return guarded


async def administrator(request: Request):
    if getattr(request.state, 'role', None) != 'admin':
        raise HTTPException(403, '请使用管理员账户管理远程连接')


async def body(request: Request):
    data = bytearray()
    async for part in request.stream():
        data.extend(part)
        if len(data) > 256 * 1024:
            raise HTTPException(413, '请求内容过大')
    try:
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (ValueError, UnicodeError):
        raise HTTPException(400, '请输入有效的操作数据') from None


@asynccontextmanager
async def lifecycle(app):
    stop = threading.Event()
    worker = threading.Thread(target=client.watch, args=(stop,), daemon=True)
    worker.start()
    yield
    stop.set()
    await asyncio.to_thread(worker.join, 4)


router = APIRouter(prefix='/api/remote-connect', tags=['remote-connect'],
                   route_class=RemoteRoute, dependencies=[Depends(administrator)], lifespan=lifecycle)


def audit(target, action):
    from app.main import audit as record
    record('remote-connect', target, action)


@router.get('')
def overview():
    return dict(rustdesk=client.status(), tailscale=tailscale.status(), nodebaby=nodebaby.status(), lan_urls=tailscale.access_urls())


@router.get('/rustdesk/settings')
def settings():
    return dict(options=client.settings())


@router.get('/rustdesk/live')
def rustdesk_live():
    return client.live()


@router.post('/rustdesk/settings')
def save_settings(value=Depends(body)):
    changes, before = value.get('changes'), value.get('before')
    if not isinstance(changes, dict) or not isinstance(before, dict):
        raise ValueError('请选择要修改的设置')
    options = client.update_settings(changes, before)
    audit('rustdesk', 'settings')
    return dict(options=options)


@router.post('/rustdesk/service')
def service(value=Depends(body)):
    action = value.get('action')
    if action not in ('start', 'stop', 'restart', 'open'):
        raise ValueError('不支持的 RustDesk 操作')
    if action in ('stop', 'restart') and value.get('confirm') is not True:
        raise ValueError('请确认操作当前 RustDesk 接入服务')
    if action == 'open':
        import subprocess
        try:
            if sys.platform == 'darwin':
                subprocess.run(['/usr/bin/open', '-a', str(client.BINARY.parents[2])], check=True, timeout=8,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen([str(client.BINARY)], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except (OSError, subprocess.SubprocessError):
            raise NativeError('无法打开 RustDesk，请检查本机安装状态') from None
    elif action == 'start':
        client.start()
        for attempt in range(20):
            try:
                client.set_accepting(True)
                break
            except NativeError:
                if attempt == 19:
                    raise
                time.sleep(.2)
    elif action == 'stop':
        client.set_accepting(False)
    else:
        client.set_accepting(False)
        client.set_accepting(True)
    audit('rustdesk', action)
    return dict(ok=True)


@router.post('/rustdesk/autostart')
def autostart(value=Depends(body)):
    enabled = value.get('enabled')
    if type(enabled) is not bool:
        raise ValueError('请选择是否自动运行 RustDesk')
    with client.lock:
        client.set_autostart(enabled)
    audit('rustdesk', 'autostart-on' if enabled else 'autostart-off')
    return dict(enabled=client.autostart())


@router.post('/rustdesk/connect')
def connect(value=Depends(body)):
    if not isinstance(value.get('target'), str):
        raise ValueError('请输入目标 RustDesk ID 或地址')
    result = client.connect(value['target'], value.get('mode', 'desktop'))
    audit(result['target'], 'rustdesk-connect-' + result['mode'])
    return result


@router.post('/rustdesk/password')
def password(value=Depends(body)):
    password = value.get('password')
    if not isinstance(password, str) or len(password) > 1024:
        raise ValueError('请输入有效的 RustDesk 密码')
    native.set_password(password)
    audit('rustdesk', 'password-update')
    return dict(ok=True)


@router.post('/rustdesk/password/temporary')
def temporary_password():
    return dict(password=native.config('temporary-password'))


@router.post('/tailscale/settings')
def tailscale_settings(value=Depends(body)):
    result = tailscale.save_preferences(value.get('changes'), value.get('before'), value.get('confirm') is True)
    audit('tailscale', 'settings')
    return dict(preferences=result)


@router.post('/tailscale/control', status_code=202)
def tailscale_control(background: BackgroundTasks, value=Depends(body)):
    result = tailscale.control(value.get('action'), value.get('confirm') is True)
    audit('tailscale', result['action'])
    # Return the acknowledgement before a requested disconnect tears down the
    # same network path used by the browser. Result remains visible via LAN.
    background.add_task(tailscale.run_operation, result['action'])
    return result


@router.post('/tailscale/ping')
def tailscale_ping(value=Depends(body)):
    return tailscale.ping(value.get('id'))


@router.post('/tailscale/netcheck')
def tailscale_netcheck():
    return tailscale.netcheck()


@router.post('/nodebaby/open')
def nodebaby_open():
    nodebaby.open_client()
    audit('nodebaby', 'open-client')
    return dict(ok=True)


@router.post('/nodebaby/probe')
def nodebaby_probe(value=Depends(body)):
    return nodebaby.probe(value.get('id'), value.get('port'))


@router.post('/nodebaby/check')
def nodebaby_check(value=Depends(body)):
    return nodebaby.check_connections(value.get('ids'))


@router.get('/lan')
def lan_status():
    from . import lan
    return lan.status()


@router.post('/lan/scan')
def lan_scan():
    from . import lan
    return lan.scan()


@router.post('/lan/note')
def lan_note(value=Depends(body)):
    from . import lan
    return lan.save_note(value.get('id'), value.get('note'))
