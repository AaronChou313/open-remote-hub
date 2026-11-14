import asyncio
from contextlib import asynccontextmanager
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import signal
import sqlite3
import subprocess
import threading
import time

import psutil
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from app.platforms import command, host, service_detail
from app import access, passwords

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / '.runtime'
DATA.mkdir(mode=0o700, exist_ok=True)
for line in (ROOT / '.env').read_text().splitlines() if (ROOT / '.env').exists() else []:
    if line and not line.startswith('#') and '=' in line:
        k,v = line.split('=',1)
        os.environ.setdefault(k.strip(), v.strip())
PORT = int(os.environ.get('ORH_PORT', '8765'))
ZPORT = int(os.environ.get('ORH_ZELLIJ_PORT', '8082'))
from app.network import Network
NETWORK = Network.load()
DB = DATA / 'metrics.sqlite3'
sessions = {}
attempts = {}
lock = threading.RLock()
latest = {}
children = {}


def db():
    return sqlite3.connect(DB, timeout=10)


def read_tasks():
    p=DATA/'tasks.json'
    return json.loads(p.read_text()) if p.exists() else {}


def save_tasks(tasks):
    p=DATA/'tasks.tmp'
    p.write_text(json.dumps(tasks,ensure_ascii=False,indent=2))
    p.chmod(0o600)
    p.replace(DATA/'tasks.json')


def task_process(task):
    try:
        p=psutil.Process(task['pid'])
        if abs(p.create_time()-task['created'])<0.01 and os.getpgid(p.pid)==p.pid and p.status()!=psutil.STATUS_ZOMBIE:
            return p
    except (KeyError, ProcessLookupError, psutil.Error):
        pass
    return None


def task_members(task):
    members={}
    p=task_process(task)
    if p:
        members[p.pid]=p
        try:
            for child in p.children(recursive=True):members[child.pid]=child
        except psutil.Error:pass
    for identity in task.get('members',[]):
        try:
            child=psutil.Process(identity['pid'])
            if abs(child.create_time()-identity['created'])<.01 and child.status()!=psutil.STATUS_ZOMBIE:
                members[child.pid]=child
        except psutil.Error:pass
    return list(members.values())


def processes():
    out=[]
    for p in psutil.process_iter():
        try:
            out.append(dict(pid=p.pid,ppid=p.ppid(),name=p.name(),cpu=p.cpu_percent(),memory=p.memory_info().rss,created=p.create_time(),command=' '.join(p.cmdline()),user=p.username()))
        except psutil.Error:
            continue
    return sorted(out,key=lambda x:(x['cpu'],x['memory']),reverse=True)


def sample():
    global latest
    previous=psutil.net_io_counters()
    before=time.monotonic()
    psutil.cpu_percent()
    while not stop_sampling.wait(3):
        try:
            now=time.time(); net=psutil.net_io_counters(); mono=time.monotonic(); dt=mono-before
            mem=psutil.virtual_memory(); disk=psutil.disk_usage(str(Path.home()))
            value=dict(time=now,cpu=psutil.cpu_percent(),memory=mem.percent,memory_used=mem.total-mem.available,memory_total=mem.total,disk=disk.percent,disk_used=disk.used,disk_total=disk.total,rx=max(0,(net.bytes_recv-previous.bytes_recv)/dt),tx=max(0,(net.bytes_sent-previous.bytes_sent)/dt))
            latest=dict(metrics=value,processes=processes())
            with db() as c:
                c.execute('INSERT INTO samples VALUES (?,?)',(now,json.dumps(value)))
                c.execute('DELETE FROM samples WHERE time < ?',(now-7*86400,))
            previous=net;before=mono
        except Exception as e:
            latest={**latest,'error':str(e)}


stop_sampling=threading.Event()
@asynccontextmanager
async def lifespan(app):
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS samples(time REAL PRIMARY KEY, data TEXT)')
    stop_sampling.clear()
    thread=threading.Thread(target=sample,daemon=True); thread.start()
    yield
    from app.native_terminal import upstream
    await upstream.close()
    from app.dsh_gateway import close as close_dsh
    await close_dsh()
    from app.ssh.jobs import shutdown as close_ssh_jobs
    await asyncio.to_thread(close_ssh_jobs)
    stop_sampling.set();thread.join(5)

app=FastAPI(title='OpenRemoteHub', lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
from app import discovery, cloud_agent
app.include_router(discovery.router)
app.include_router(cloud_agent.router)

@app.middleware('http')
async def security(request:Request, call_next):
    authority=request.headers.get('host', '')
    scheme=request.url.scheme
    if not NETWORK.allows(authority,PORT,scheme):
        return JSONResponse({'detail':'Invalid host'},400)
    origin=request.headers.get('origin')
    discovery_read = request.url.path == discovery.PATH and request.method in ('GET', 'HEAD', 'OPTIONS')
    if origin and not NETWORK.same_origin(authority,origin,PORT,scheme) and not (discovery_read and discovery.allowed_origin(origin)):
        return JSONResponse({'detail':'Cross-origin request denied'},403)
    native=request.url.path.startswith('/terminal/')
    if native and request.method not in ('GET','HEAD') and not NETWORK.same_origin(authority,origin,PORT,scheme):
        return JSONResponse({'detail':'Terminal origin required'},403)
    if not native and request.method not in ('GET','HEAD','OPTIONS') and request.headers.get('x-orh-request')!='1':
        return JSONResponse({'detail':'Missing CSRF header'},403)
    if request.url.path.startswith('/api/') and request.url.path not in ('/api/login','/api/auth/status','/api/auth/setup'):
        s=access.get(request.cookies.get('orh',''))
        if not s or s['expires']<time.time():
            return JSONResponse({'detail':'请登录'},401)
        request.state.role=s['role']
        if request.method!='GET' and request.url.path!='/api/logout' and s['role']!='admin':
            return JSONResponse({'detail':'只读账户无操作权限'},403)
    response=await call_next(request)
    response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer','Content-Security-Policy':f"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-src 'none'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
    if request.url.path=='/' and os.environ.get('ORH_DSH_ENABLED')=='1':
        from app.dsh import settings
        hostname=request.url.hostname
        gateway=f"{request.url.scheme}://{f'[{hostname}]' if ':' in hostname else hostname}:{settings()['gateway_port']}"
        response.headers['Content-Security-Policy']=response.headers['Content-Security-Policy'].replace("frame-src 'none'","frame-src "+gateway)
    if native:
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; connect-src 'self'; img-src 'self' data:; worker-src 'self' blob:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    return response


class Login(BaseModel):
    password:str


def throttle(request):
    now=time.time();ip=request.client.host
    with lock:
        attempts[ip]=[t for t in attempts.get(ip,[]) if t>now-60]
        if len(attempts[ip])>=8: raise HTTPException(429,'尝试过多，请一分钟后重试')
        attempts[ip].append(now)


def login_response(request,expires=None):
    expires = min(expires or time.time()+43200,time.time()+43200)
    token=secrets.token_urlsafe(32);access.create(token,'admin',expires)
    result=JSONResponse({'role':'admin'})
    result.set_cookie('orh',token,httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=max(1,int(expires-time.time())))
    return result

@app.get('/api/auth/status')
def auth_status():
    return {'needs_setup':not cloud_agent.binding() and passwords.record() is None,'cloud':{key:cloud_agent.status()[key] for key in ('bound','cloud_url')}}

@app.post('/api/auth/setup')
def setup(body:Login,request:Request):
    if cloud_agent.binding():raise HTTPException(409,'设备已绑定 Cloud，请使用 Cloud 登录')
    # First-use setup is restricted to an actual loopback connection and exact origin.
    if request.url.hostname not in ('localhost','127.0.0.1','::1') or request.client.host not in ('127.0.0.1','::1') or not NETWORK.same_origin(request.headers.get('host',''),request.headers.get('origin'),PORT,request.url.scheme):
        raise HTTPException(403,'请在本机浏览器设置密码，或使用本机 password.py 脚本')
    throttle(request)
    passwords.save(body.password,initial=True)
    return login_response(request)

@app.post('/api/login')
def login(body:Login,request:Request):
    if cloud_agent.binding():raise HTTPException(409,'请使用 Cloud 账号登录此设备')
    throttle(request)
    if not passwords.verify(body.password):raise HTTPException(401,'密码错误')
    return login_response(request)

@app.post('/api/auth/password')
def change_password(body:Login,request:Request):
    if cloud_agent.binding():raise HTTPException(409,'Cloud 绑定模式请在 Cloud 管理账号')
    with passwords.lock:
        passwords.save(body.password)
    return login_response(request)

@app.post('/api/logout')
def logout(request:Request):
    access.revoke(request.cookies.get('orh',''))
    r=JSONResponse({'ok':True});r.delete_cookie('orh');return r

@app.get('/api/me')
def me(request:Request): return {'role':request.state.role,'host':host.info(),'zellij_port':ZPORT,'cloud':cloud_agent.status()}

@app.get('/api/system')
def system(): return {**latest,'host':host.info()}

@app.get('/api/history')
def history(hours:int=1):
    hours=max(1,min(hours,168))
    with db() as c:
        rows=c.execute('SELECT data FROM samples WHERE time>? ORDER BY time',(time.time()-hours*3600,)).fetchall()
    values=[json.loads(x[0]) for x in rows]
    # Bound chart payload while retaining peaks in each bucket.
    step=max(1,len(values)//600)
    return [max(values[i:i+step],key=lambda x:x['cpu']) for i in range(0,len(values),step)]


def cli(args,timeout=20,cwd=None):
    try:return command(args,timeout,cwd=cwd) if cwd is not None else command(args,timeout)
    except RuntimeError as e:raise HTTPException(503,str(e))


def jsonlines(s): return [json.loads(x) for x in s.splitlines() if x.strip()]

@app.get('/api/docker')
def docker_list():
    containers=jsonlines(cli(['docker','ps','-a','--no-trunc','--format','{{json .}}']))
    if containers:
        bindings=cli(['docker','inspect','--format','{{.Id}} {{json .HostConfig.PortBindings}}',*[c['ID'] for c in containers]])
        ports={}
        for row in bindings.splitlines():
            identifier,raw=row.split(' ',1)
            mapping=json.loads(raw) or {}
            ports[identifier]=', '.join(f"{b.get('HostIp') or '0.0.0.0'}:{b.get('HostPort') or '动态'} → {port}" for port,entries in mapping.items() for b in (entries or []))
        for c in containers:c['ConfiguredPorts']=ports.get(c['ID'],'')
    images=jsonlines(cli(['docker','image','ls','--format','{{json .}}']))
    stats=jsonlines(cli(['docker','stats','--no-stream','--format','{{json .}}'],30))
    return dict(containers=containers,images=images,stats=stats)


def container_id(value):
    if not re.fullmatch('[a-f0-9]{12,64}',value):raise HTTPException(400,'Invalid container ID')
    return value

@app.get('/api/docker/{identifier}')
def docker_detail(identifier:str):
    d=json.loads(cli(['docker','inspect',container_id(identifier)]))[0]
    return {k:d.get(k) for k in ('Id','Name','State','Mounts','NetworkSettings','Path','Args')}

class Action(BaseModel):
    action:str
    confirm:str=''
    name:str=''


def confirmed(body,target):
    if body.confirm!=target:raise HTTPException(400,'必须确认目标名称')


def audit(kind,target,action):
    with (DATA/'audit.jsonl').open('a') as f:f.write(json.dumps(dict(time=time.time(),kind=kind,target=target,action=action))+'\n')

@app.post('/api/docker/{identifier}')
def docker_action(identifier:str,body:Action):
    container_id(identifier);confirmed(body,identifier)
    if body.action not in ('start','stop','restart'):raise HTTPException(400,'Unsupported action')
    out=cli(['docker',body.action,identifier],40);audit('docker',identifier,body.action);return {'output':out}

@app.get('/api/docker/{identifier}/logs')
def logs(identifier:str,request:Request,follow:bool=False):
    container_id(identifier)
    if not follow:
        p=subprocess.run(['docker','logs','--tail','200','--timestamps',identifier],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=15)
        return {'output':p.stdout[-65536:]}
    async def stream():
        p=await asyncio.create_subprocess_exec('docker','logs','--tail','100','--timestamps','--follow',identifier,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT)
        try:
            while True:
                if await request.is_disconnected():break
                try:line=await asyncio.wait_for(p.stdout.readline(),1)
                except asyncio.TimeoutError:
                    yield ': heartbeat\n\n';continue
                if not line:break
                yield 'data: '+json.dumps(line.decode(errors='replace'))+'\n\n'
        finally:
            if p.returncode is None:
                p.terminate();await p.wait()
    return StreamingResponse(stream(),media_type='text/event-stream')


def zname(name):
    # macOS Unix socket paths are limited; long names can vanish from discovery.
    limit=20 if host.info()['system']=='Darwin' else 48
    if len(name)>limit:raise HTTPException(400,f'本平台会话名称最长 {limit} 字符（Unix socket 路径限制）')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',name):raise HTTPException(400,'会话名仅支持字母、数字、点、下划线、短横线，最长受平台 socket 路径限制')
    return name

@app.get('/api/zellij')
def zellij_list():
    from app.zellij_sessions import discover,host_sessions
    entries,warning=discover()
    live={s['name']:s for s in host_sessions() if s['status']=='running'}
    for entry in entries:
        if entry['name'] in live:entry['pid']=live[entry['name']]['pid']
    return dict(sessions=entries,warning=warning)

@app.post('/api/zellij/{name}')
def zellij_action(name:str,body:Action):
    zname(name);confirmed(body,name)
    from app.zellij_manage import mutate
    result=mutate(name,body.action,body.name)
    audit('zellij',name,body.action)
    return result

@app.post('/api/zellij-web')
def zellij_web(body:Action):
    confirmed(body,'zellij-web')
    if body.action=='start':
        try:out=command(['zellij','web','--status','--timeout','2','--ip','127.0.0.1','--port',str(ZPORT)],4)
        except RuntimeError:out=cli(['zellij','web','--start','--daemonize','--ip','127.0.0.1','--port',str(ZPORT)])
    elif body.action=='token':out=cli(['zellij','web','--create-token'])
    else:raise HTTPException(400,'Unsupported action')
    audit('zellij-web','local',body.action);return {'output':out}

@app.get('/api/services')
def services():
    try:return {'services':host.services()}
    except RuntimeError as e:raise HTTPException(503,str(e))

@app.get('/api/services/{name}')
def service_info(name:str):
    try:return service_detail(name)
    except RuntimeError as e:raise HTTPException(404,str(e))

class Task(BaseModel):
    name:str=Field(min_length=1,max_length=80)
    argv:list[str]=Field(default_factory=list,max_length=64)
    command:str=Field(default='',max_length=8192)
    cwd:str

@app.get('/api/tasks')
def tasks_list():
    with lock:
        return [dict(id=k,**v,running=bool(task_members(v))) for k,v in read_tasks().items()]

@app.post('/api/tasks')
def task_create(body:Task):
    if not Path(body.cwd).is_dir() or not Path(body.cwd).is_absolute():raise HTTPException(400,'工作目录须为有效绝对路径')
    if body.command:
        if body.argv:raise HTTPException(400,'命令和参数数组请选择一种填写')
        try:
            lexer=shlex.shlex(body.command,posix=True,punctuation_chars=';&|<>')
            lexer.whitespace_split=True;lexer.commenters=''
            body.argv=list(lexer)
        except ValueError as e:raise HTTPException(400,'命令引号不完整：'+str(e))
        if any(re.fullmatch(r'[;&|<>]+',arg) for arg in body.argv):
            raise HTTPException(400,'这里直接启动程序，不解释管道或重定向；需要 Shell 时请显式使用 /bin/zsh -lc 并将完整命令放入引号')
    if not body.argv or len(body.argv)>64 or not body.argv[0] or any('\x00' in x or len(x)>8192 for x in body.argv):raise HTTPException(400,'请输入有效启动命令')
    with lock:
        tasks=read_tasks();key=secrets.token_hex(8);tasks[key]=body.model_dump();save_tasks(tasks)
    audit('task',key,'create');return {'id':key}

@app.post('/api/tasks/{key}')
def task_action(key:str,body:Action):
    confirmed(body,key)
    with lock:
        tasks=read_tasks()
        if key not in tasks:raise HTTPException(404,'Task not found')
        t=tasks[key];p=task_process(t);members=task_members(t)
        if body.action not in ('start','stop','restart','delete'):raise HTTPException(400,'Unsupported action')
        if body.action=='delete':
            if members:raise HTTPException(409,'请先停止任务')
            del tasks[key]
        else:
            if body.action in ('stop','restart') and members:
                t['members']=[dict(pid=x.pid,created=x.create_time()) for x in members]
                save_tasks(tasks) # retain verified identities even if the leader exits first
                if p:
                    try:os.killpg(p.pid,signal.SIGTERM)
                    except ProcessLookupError:pass
                else:
                    for member in members:
                        try:member.terminate()
                        except psutil.NoSuchProcess:pass
                psutil.wait_procs(members,timeout=5)
                if task_members(t):
                    raise HTTPException(409,'任务组仍有进程未退出；已阻止重启，未强制结束，请检查日志')
                t['members']=[]
            if body.action in ('start','restart'):
                if body.action=='start' and members:raise HTTPException(409,'任务已运行')
                logfile=DATA/f'task-{key}.log'
                if logfile.exists() and logfile.stat().st_size>10*1024*1024:logfile.replace(DATA/f'task-{key}.previous.log')
                with logfile.open('ab') as f:
                    try:child=subprocess.Popen(t['argv'],cwd=t['cwd'],stdout=f,stderr=f,stdin=subprocess.DEVNULL,start_new_session=True)
                    except OSError as e:raise HTTPException(400,str(e))
                children[key]=child
                t['pid']=child.pid;t['created']=psutil.Process(child.pid).create_time()
            for k in list(children):
                if children[k].poll() is not None:children.pop(k)
        save_tasks(tasks)
    audit('task',key,body.action);return {'ok':True}

@app.get('/api/tasks/{key}/logs')
def task_logs(key:str):
    if key not in read_tasks():raise HTTPException(404,'Task not found')
    p=DATA/f'task-{key}.log'
    if not p.exists():return {'output':'任务尚无日志'}
    with p.open('rb') as f:
        f.seek(max(0,p.stat().st_size-65536));return {'output':f.read().decode(errors='replace')}

@app.get('/')
def index():return FileResponse(ROOT/'static/index.html')
from app.dsh import router as dsh_router
app.include_router(dsh_router)
from app.environments import router as environments_router
app.include_router(environments_router)
from app.projects import router as projects_router
app.include_router(projects_router)
from app.files import router as files_router
app.include_router(files_router)
from app.knowledge import router as knowledge_router
app.include_router(knowledge_router)
from app.remote_connect.api import router as remote_connect_router
app.include_router(remote_connect_router)
from app.applications import router as applications_router
app.include_router(applications_router)
from app.local_services import router as local_services_router
app.include_router(local_services_router)
from app.native_terminal import router as native_router
app.include_router(native_router)
from app.terminal_browser import router as terminal_browser_router
app.include_router(terminal_browser_router)
from app.proxy import router as proxy_router
app.include_router(proxy_router)
from app.proxy_manager import router as proxy_manager_router
app.include_router(proxy_manager_router)
from app.ssh.api import router as ssh_router
app.include_router(ssh_router)
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
