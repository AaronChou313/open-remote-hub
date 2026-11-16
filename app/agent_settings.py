"""Agent access and opt-in local recovery, independent of Cloud and Mesh."""
import json
import os
import subprocess
import sys
import threading
from dataclasses import replace

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from app.network import Network
from app.remote_connect.api import administrator

router = APIRouter(prefix='/api/agent/settings', dependencies=[Depends(administrator)])
lock = threading.RLock()


def path():
    from app.main import DATA
    return DATA / 'agent-settings.json'


def load():
    return json.loads(path().read_text()) if path().exists() else {}


def save(value):
    with lock:
        temporary = path().with_suffix('.tmp')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            json.dump(value, output)
        temporary.replace(path())


def recovery_enabled():
    return bool(load().get('recovery_enabled'))


def configured_network(default):
    value = load()
    return Network.configured(value['bind'], value['allowed_hosts']) if 'bind' in value else default


@router.get('')
def status():
    from app import main, passwords
    network = configured_network(main.NETWORK)
    scheme = 'https' if os.environ.get('ORH_TLS_CERT_FILE') else 'http'
    hosts = sorted(network.hosts - {'localhost', '127.0.0.1', '::1'})
    return dict(bind=network.bind, active_bind=main.NETWORK.bind, allowed_hosts=hosts,
                restart_required=network.bind != main.NETWORK.bind,
                restart_supported=bool(getattr(sys, 'frozen', False)),
                recovery_enabled=recovery_enabled(), password_set=passwords.record() is not None,
                urls=[f'{scheme}://{f"[{host}]" if ":" in host else host}:{main.PORT}' for host in hosts])


class Settings(BaseModel):
    bind: str = Field(max_length=128)
    allowed_hosts: list[str] = Field(max_length=64)
    recovery_enabled: bool
    password: str = Field(default='', max_length=1024)


@router.post('')
def update(body: Settings):
    from app import main, passwords
    try:
        network = Network.configured(body.bind, body.allowed_hosts)
    except ValueError as error:
        raise HTTPException(400, str(error)) from None
    with lock:
        if body.recovery_enabled and not recovery_enabled() and not body.password:
            raise HTTPException(400, '启用本地恢复时请设置独立的恢复密码')
        if body.password:
            if len(body.password) < 8:
                raise HTTPException(400, '恢复密码至少需要 8 个字符')
            passwords.save(body.password)
        save(dict(bind=network.bind, allowed_hosts=body.allowed_hosts, recovery_enabled=body.recovery_enabled))
        # Allowed destinations take effect immediately. Changing the listener
        # requires a restart, while the current authenticated request completes.
        main.NETWORK = replace(main.NETWORK, hosts=network.hosts)
    main.audit('agent', 'access', 'configure')
    return status()


@router.post('/restart')
def restart(background: BackgroundTasks):
    from app import launcher
    if not getattr(sys, 'frozen', False):
        raise HTTPException(409, '源码运行时请通过当前服务管理器重启 Agent')
    background.add_task(subprocess.Popen, launcher.command('--restart-agent'),
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        start_new_session=sys.platform != 'win32', creationflags=launcher.CREATE_NO_WINDOW)
    return dict(ok=True)
