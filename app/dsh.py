"""Lifecycle adapter for the installed DeepSeek Harness, never an agent reimplementation."""
import json
import os
from pathlib import Path
import shutil
import plistlib
import re
import socket
import subprocess
import threading
import time
import httpx
import psutil
from fastapi import APIRouter, Depends, HTTPException
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


def installation():
    explicit=os.environ.get('ORH_DSH_BIN')
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
        if not any('/@deepseek-ai/dsh/' in a or '/@deepseek-ai/dsh-desktop-host/' in a or Path(a).name=='dsh' for a in args):continue
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
        if record['port']==settings()['port'] and managed():
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


@router.get('/status')
def status():
    cfg=settings();installed=installation();p=managed()
    if not p and cfg['enabled']:p=listener()
    version=installed['version'] if installed else None
    if managed():
        try:version=json.loads(state_path().read_text()).get('version',version)
        except (OSError,ValueError):pass
    return dict(enabled=cfg['enabled'],installed=bool(installed),version=version,gateway_port=cfg['gateway_port'],running=bool(p and healthy()),managed=bool(managed()),pid=p.pid if p else None)


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
            raise HTTPException(409,'DSH 进程存在但尚未就绪，未重复启动或终止它；请稍后重试')
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1',cfg['port']))==0:raise HTTPException(409,'DSH 内部端口已占用，未连接未知服务')
        argv=info['argv']+['web','--patch',str(main.ROOT/'config/dsh-web.patch.yml'),'--host','127.0.0.1','--port',str(cfg['port']),'--no-open']
        plan=main.DATA/'dsh-launch.json'
        plan.write_text(json.dumps(dict(argv=argv,home=cfg['home'],port=cfg['port'],data=str(main.DATA))))
        plan.chmod(0o600)
        wrapper=[str(main.ROOT/'.venv/bin/python'),str(main.ROOT/'scripts/dsh_host.py'),str(plan)]
        env={k:v for k,v in os.environ.items() if not k.startswith('ORH_')}
        log=main.DATA/'dsh-supervisor.log'
        fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600);os.fchmod(fd,0o600)
        with os.fdopen(fd,'ab') as f:
            child=subprocess.Popen(wrapper,cwd=str(Path.home()),env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True)
        identity=dict(pid=child.pid,created=psutil.Process(child.pid).create_time(),argv=wrapper,version=info['version'])
        temp=state_path().with_suffix('.tmp');temp.write_text(json.dumps(identity));temp.chmod(0o600);temp.replace(state_path())
        for _ in range(80):
            if child.poll() is not None:raise HTTPException(503,'DSH 启动失败；本机私有 .runtime/dsh.log 中保留日志')
            if healthy():
                main.audit('dsh','web','start');return status()
            time.sleep(.2)
        raise HTTPException(504,'DSH 尚未完成启动，进程已保留；请重试连接，不会重复启动')
