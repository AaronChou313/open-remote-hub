"""One user action prepares a native terminal; never force-runs saved commands."""
from pathlib import Path
import threading
import time
import httpx
from fastapi import HTTPException
from app.zellij_sessions import host_sessions

lock = threading.RLock()
web_lock = threading.RLock()
session_locks = {}


def ensure_web():
    with web_lock:
        return _ensure_web()


def _ensure_web():
    from app import main
    url=f'http://127.0.0.1:{main.ZPORT}/info/version'
    with httpx.Client(timeout=1,trust_env=False) as c:
        try:
            if c.get(url).status_code==200:return
        except httpx.HTTPError:pass
        main.cli(['zellij','web','--start','--daemonize','--ip','127.0.0.1','--port',str(main.ZPORT)],8)
        for _ in range(15):
            try:
                if c.get(url).status_code==200:return
            except httpx.HTTPError:pass
            time.sleep(.1)
    raise HTTPException(503,'终端 Web 服务启动失败；可直接在此页重试，无需返回控制台')


def prepare(name):
    from app import main
    main.zname(name)
    with lock:
        session_lock=session_locks.setdefault(name,threading.RLock())
    with session_lock:
        entries=host_sessions()
        existing=next((s for s in entries if s['name']==name),None)
        state='reused'
        if not existing or existing['status']!='running':
            # No --force-run-commands: archived programs remain held by Zellij.
            main.cli(['zellij','--config',str(main.ROOT/'config/zellij.kdl'),'attach','--create-background',name],8,**({'cwd':str(Path.home())} if not existing else {}))
            state='restored' if existing else 'created'
            for _ in range(20):
                if any(s['name']==name and s['status']=='running' for s in host_sessions()):break
                time.sleep(.1)
            else:raise HTTPException(503,'会话尚未准备好，请直接在此页重试')
        ensure_web()
        main.audit('terminal',name,'enter-'+state)
        return {'url':'/terminal/'+name,'state':state,'session':name}
