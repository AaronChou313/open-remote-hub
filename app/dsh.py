"""Lifecycle adapter for the installed DeepSeek Harness, never an agent reimplementation."""
import json
import os
from pathlib import Path
import shutil
import plistlib
import re
import socket
import subprocess
import sys
import threading
import time
import httpx
import psutil
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.access import admin

router=APIRouter(prefix='/api/dsh',dependencies=[Depends(admin)])
mutex=threading.RLock()


def settings():
    from app import main
    enabled=os.environ.get('ORH_DSH_ENABLED','0')=='1'
    gateway=int(os.environ.get('ORH_DSH_GATEWAY_PORT','8767'))
    upstream=int(os.environ.get('ORH_DSH_PORT','9741'))
    if enabled and (not all(1024<=p<=65535 for p in (gateway,upstream)) or len({main.PORT,main.ZPORT,gateway,upstream})!=4):
        raise ValueError('DSH ports must be distinct, unprivileged ports')
    return dict(enabled=enabled,gateway_port=gateway,port=upstream,home=str(Path(os.environ.get('ORH_DSH_HOME',str(Path.home()/'.dsh'))).expanduser().resolve()))


def windows_desktop_installation():
    from app.programs import windows_install_directory
    folders = [windows_install_directory('DeepSeek Harness')]
    for variable in ('LOCALAPPDATA', 'ProgramFiles'):
        if os.environ.get(variable):
            relative = 'Programs/DeepSeek Harness' if variable == 'LOCALAPPDATA' else 'DeepSeek Harness'
            folders.append(Path(os.environ[variable]) / relative)
    for folder in folders:
        if folder is None:
            continue
        executable = folder / 'DeepSeek Harness.exe'
        resources = folder / 'resources'
        launcher = resources / 'runtime/cli/bin/dsh.cmd'
        if not (executable.is_file() and launcher.is_file() and (resources / 'app.asar').is_file()):
            continue
        # This is the argv/env used by Desktop's own dsh.cmd launcher. Electron
        # resolves its packaged ASAR entry while running its bundled Node runtime.
        entry = resources / 'app.asar/dsh/node_modules/@deepseek-ai/dsh-desktop-host/lib/cli.js'
        argv = [str(executable), '--expose-internals', str(entry)]
        environment = {'ELECTRON_RUN_AS_NODE':'1'}
        try:
            result = subprocess.run(argv + ['--version'], capture_output=True, text=True, timeout=4,
                                    env={**os.environ, **environment}, creationflags=subprocess.CREATE_NO_WINDOW)
            version = result.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            continue
        match = re.match(r'^(\d+)\.(\d+)\.(\d+)', version)
        if result.returncode == 0 and match and tuple(map(int, match.groups())) >= (0,2,0):
            return dict(argv=argv, env=environment, version=version)
    return None


def installation():
    explicit=os.environ.get('ORH_DSH_BIN')
    if sys.platform == 'win32' and not explicit:
        desktop = windows_desktop_installation()
        if desktop:
            return desktop
    candidates=[]
    if explicit:candidates.append((Path(explicit).expanduser(),None))
    else:
        # The desktop distribution includes the supported CLI; it need not be
        # installed into the service's PATH. Never silently prefer an old npx cache.
        bundle=Path('/Applications/DeepSeek Harness.app/Contents')
        launcher=bundle/'Resources/runtime/cli/bin/dsh'
        if launcher.is_file():
            try:candidates.append((launcher,plistlib.loads((bundle/'Info.plist').read_bytes()).get('CFBundleShortVersionString')))
            except (OSError,ValueError):pass
        binary=shutil.which('dsh')
        if binary:candidates.append((Path(binary),None))
        candidates.extend((p,None) for p in (Path.home()/'.npm/_npx').glob('*/node_modules/@deepseek-ai/dsh/lib/bin.js'))
    found=[]
    for entry,version in candidates:
        if not entry.is_file():continue
        node=shutil.which('node')
        if entry.suffix=='.js' and not node:continue
        argv=[node,str(entry.resolve())] if entry.suffix=='.js' else [str(entry.resolve())]
        if not version:
            try:
                manifest=json.loads((entry.resolve().parent.parent/'package.json').read_text())
                if manifest.get('name')=='@deepseek-ai/dsh':version=manifest['version']
            except (OSError,ValueError,KeyError):pass
        if not version:
            try:version=subprocess.run(argv+['--version'],capture_output=True,text=True,timeout=3).stdout.strip()[:100]
            except (OSError,subprocess.TimeoutExpired):continue
        match=re.match(r'^(\d+)\.(\d+)\.(\d+)',version or '')
        if not match:continue
        key=tuple(map(int,match.groups()))
        if key<(0,2,0):continue
        found.append((key,dict(argv=argv,version=version)))
    return max(found,key=lambda row:row[0])[1] if found else None


def state_path():
    from app.main import DATA
    return DATA/'dsh-process.json'


def managed():
    try:
        data=json.loads(state_path().read_text());p=psutil.Process(data['pid'])
        if abs(p.create_time()-data['created'])<0.01 and p.status()!=psutil.STATUS_ZOMBIE and p.cmdline()[1:]==data['argv'][1:]:
            return p
    except (OSError,ValueError,KeyError,psutil.Error):pass
    return None


def listener():
    """Identify an existing DSH listener before reusing it; do not trust a port alone."""
    cfg=settings()
    for p in psutil.process_iter(['pid','cmdline']):
        args=p.info['cmdline'] or []
        normalized = [argument.replace('\\', '/') for argument in args]
        if not any('/@deepseek-ai/dsh/' in a or '/@deepseek-ai/dsh-desktop-host/' in a or Path(a).name in ('dsh','dsh.cmd') for a in normalized):continue
        try:
            candidates=[p,*p.children(recursive=True)]
            for child in candidates:
                if any(c.status=='LISTEN' and c.laddr.ip=='127.0.0.1' and c.laddr.port==cfg['port'] for c in child.net_connections('inet')):return p
        except psutil.Error:continue
    return None


def native_cookie():
    from app.main import DATA
    try:
        record=json.loads((DATA/'dsh-auth.json').read_text())
        # The cookie is the credential; process ownership is bookkeeping. Gating
        # here on managed() blanks a perfectly valid cookie whenever the PID /
        # create-time / start-script check drifts (a relaunched console, a clock
        # step, a recycled PID) and turns the whole DSH pane into a 503. Let the
        # native host decide: an invalid cookie simply 401s upstream.
        if record['port']==settings()['port']:
            if record.get('launch_token') and time.time()>record.get('renew_after',0):
                with mutex:
                    record=json.loads((DATA/'dsh-auth.json').read_text())
                    if time.time()>record.get('renew_after',0):
                        from app.dsh_auth import exchange,save
                        try:record=exchange(record['port'],record['launch_token']);save(DATA,record)
                        except (httpx.HTTPError,RuntimeError):pass
            return record['cookie']
    except (OSError,ValueError,KeyError):pass
    return ''


def healthy():
    try:
        with httpx.Client(trust_env=False,timeout=1) as c:r=c.get(f"http://127.0.0.1:{settings()['port']}/",headers={'Cookie':native_cookie()})
        return r.status_code==200 and ('dsh' in r.text.lower() or 'deepseek' in r.text.lower())
    except httpx.HTTPError:return False


def recover():
    """Re-exchange the stored launch token; the only sanctioned way to revive a stale cookie."""
    from app.main import DATA
    try:record=json.loads((DATA/'dsh-auth.json').read_text())
    except (OSError,ValueError):record={}
    if not record.get('launch_token'):
        record=adopt_supervisor() or record
    if record.get('port')!=settings()['port'] or not record.get('launch_token'):return False
    from app.dsh_auth import exchange,save
    try:save(DATA,exchange(record['port'],record['launch_token']))
    except (httpx.HTTPError,RuntimeError):return False
    return True


def adopt_supervisor():
    """Recover credentials from this user's already running ORH DSH supervisor."""
    from app.main import DATA
    from app.dsh_auth import save
    for process in psutil.process_iter(['pid','cmdline','username']):
        args=process.info['cmdline'] or []
        if not any(Path(arg).name=='dsh_host.py' for arg in args):continue
        try:
            if process.username()!=psutil.Process().username():continue
            plan=json.loads(Path(args[-1]).read_text())
            if plan['port']!=settings()['port']:continue
            folder=Path(plan['data'])
            identity=json.loads((folder/'dsh-process.json').read_text())
            if identity['pid']!=process.pid or abs(identity['created']-process.create_time())>=.01:continue
            record=json.loads((folder/'dsh-auth.json').read_text())
            if record.get('port')!=plan['port'] or not record.get('launch_token'):continue
            save(DATA,record)
            state_path().write_text(json.dumps(identity))
            state_path().chmod(0o600)
            return record
        except (OSError,ValueError,KeyError,psutil.Error):continue
    return None


@router.get('/status')
def status():
    cfg=settings();installed=installation();p=managed()
    if not p and cfg['enabled']:p=listener()
    version=installed['version'] if installed else None
    if managed():
        try:version=json.loads(state_path().read_text()).get('version',version)
        except (OSError,ValueError):pass
    running=bool(p and (healthy() or recover() and healthy()))
    state='disabled' if not cfg['enabled'] else 'missing_dependency' if not installed else 'running' if running else 'needs_auth' if p else 'stopped'
    return dict(enabled=cfg['enabled'],installed=bool(installed),version=version,gateway_port=cfg['gateway_port'],running=running,state=state,managed=bool(managed()),pid=p.pid if p else None)


@router.post('/start')
def start():
    from app import main
    with mutex:
        cfg=settings()
        if not cfg['enabled']:raise HTTPException(409,'请在本机 .env 设置 ORH_DSH_ENABLED=1 后重启控制台')
        info=installation()
        if not info:raise HTTPException(503,'未发现本机 DSH；请配置 ORH_DSH_BIN，不会自动下载或升级')
        existing=managed() or listener()
        if existing:
            if healthy():return status()
            if recover() and healthy():
                main.audit('dsh','web','recover');return status()
            raise HTTPException(409,'DSH 正在运行，认证恢复未成功。可在此页重试认证；ORH 管理的进程支持单独重启 DSH。外部启动的实例请先在原客户端退出，再回到此页启动。')
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1',cfg['port']))==0:raise HTTPException(409,'DSH 内部端口已占用，未连接未知服务')
        argv=info['argv']+['web','--patch',str(main.ROOT/'config/dsh-web.patch.yml'),'--host','127.0.0.1','--port',str(cfg['port']),'--no-open']
        plan=main.DATA/'dsh-launch.json'
        plan.write_text(json.dumps(dict(argv=argv,env=info.get('env',{}),home=cfg['home'],port=cfg['port'],data=str(main.DATA))))
        plan.chmod(0o600)
        from app.runtime import script
        wrapper=script('dsh_host.py',plan)
        env={k:v for k,v in os.environ.items() if not k.startswith('ORH_')}
        log=main.DATA/'dsh-supervisor.log'
        fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        os.chmod(log,0o600)
        with os.fdopen(fd,'ab') as f:
            child=subprocess.Popen(wrapper,cwd=str(Path.home()),env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=f,
                                   start_new_session=sys.platform!='win32',
                                   creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if sys.platform=='win32' else 0)
        identity=dict(pid=child.pid,created=psutil.Process(child.pid).create_time(),argv=wrapper,version=info['version'])
        temp=state_path().with_suffix('.tmp');temp.write_text(json.dumps(identity));temp.chmod(0o600);temp.replace(state_path())
        for _ in range(80):
            if child.poll() is not None:raise HTTPException(503,'DSH 启动失败；本机私有 .runtime/dsh.log 中保留日志')
            if healthy():
                main.audit('dsh','web','start');return status()
            time.sleep(.2)
        raise HTTPException(504,'DSH 尚未完成启动，进程已保留；请重试连接，不会重复启动')


@router.post('/recover')
def recover_connection():
    with mutex:
        if not recover() or not healthy():
            raise HTTPException(409,'未能恢复 DSH 认证。ORH 管理的实例可单独重启；外部实例请先在原客户端退出，再从此页启动。')
        return status()


class RestartRequest(BaseModel):
    confirm: bool = False


@router.post('/restart')
def restart(body: RestartRequest):
    with mutex:
        if not body.confirm:raise HTTPException(400,'请确认重启 DSH，正在运行的模型任务会中断')
        process=managed()
        if not process:raise HTTPException(409,'此 DSH 实例由其他软件启动，请先在原客户端退出')
        try:
            children=process.children(recursive=True)
            if sys.platform == 'win32':
                # TerminateProcess does not deliver SIGTERM to the supervisor.
                # Stop its owned child tree so the log reader exits on EOF.
                for child in reversed(children):
                    try:child.terminate()
                    except psutil.NoSuchProcess:pass
            else:
                process.terminate()
            _,alive=psutil.wait_procs([process,*children],timeout=8)
            if alive:raise HTTPException(409,'DSH 尚未退出，请稍后重试')
        except psutil.NoSuchProcess:pass
        state_path().unlink(missing_ok=True)
        from app.main import DATA
        (DATA/'dsh-auth.json').unlink(missing_ok=True)
        return start()
