"""Private profile library and authenticated, bounded commands to the proxy broker."""
import asyncio
from contextlib import contextmanager
import fcntl
import hashlib
import ipaddress
import json
import os
import shlex
from pathlib import Path
import socket
import tempfile
import time
from urllib.parse import urljoin, urlsplit
import uuid
import httpx
import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

router=APIRouter(prefix='/api/proxy/manager',tags=['proxy-manager'])
lock=asyncio.Lock()
LIMIT=3*1024*1024


def root():
    from app.main import DATA
    path=DATA/'proxy'
    path.mkdir(parents=True,mode=0o700,exist_ok=True)
    path.chmod(0o700)
    return path


def settings():
    path=root()/'connection.json'
    return json.loads(path.read_text()) if path.exists() else {}


def client():
    path=settings().get('socket')
    if not path or not Path(path).is_absolute(): raise HTTPException(503,'代理后台尚未安装，请在主机运行代理安装命令')
    return httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=path),base_url='http://localhost',timeout=70,trust_env=False)


async def call(method,path,body=None):
    try:
        async with client() as c:
            r=await c.request(method,path,json=body)
            if len(r.content)>8*1024*1024: raise HTTPException(502,'代理响应过大')
            data=r.json()
            if r.status_code>=400: raise HTTPException(r.status_code,data.get('detail','代理操作失败'))
            return data
    except (httpx.HTTPError,ValueError) as e: raise HTTPException(503,'代理后台不可达，请在主机检查服务状态') from e


def atomic(path,value):
    fd,name=tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:
            json.dump(value,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


@contextmanager
def disk_lock():
    with (root()/'library.lock').open('a') as f:
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise HTTPException(409,'另一项代理配置操作正在执行，请稍后重试')
        try:yield
        finally:fcntl.flock(f,fcntl.LOCK_UN)


def library():
    path=root()/'profiles.json'
    return json.loads(path.read_text()) if path.exists() else {'active':None,'profiles':[]}


def rev(profile):
    return hashlib.sha256(json.dumps(profile,sort_keys=True).encode()).hexdigest()


def find(data,key,revision=None):
    row=next((x for x in data['profiles'] if x['id']==key),None)
    if not row:raise HTTPException(404,'配置不存在')
    if revision is not None and rev(row)!=revision:raise HTTPException(409,'配置已被修改，请刷新后重试')
    return row


class Loader(yaml.SafeLoader):
    count=0
    def compose_node(self,parent,index):
        self.count+=1
        if self.count>100000 or self.check_event(yaml.AliasEvent):raise yaml.YAMLError('配置过于复杂或包含别名')
        return super().compose_node(parent,index)


def parse(text):
    if len(text.encode())>LIMIT:raise HTTPException(413,'配置最大为 3 MiB')
    try:
        data=yaml.load(text,Loader=Loader)
        if not isinstance(data,dict) or not all(isinstance(k,str) for k in data):raise ValueError()
        if not data.get('proxies') and not data.get('proxy-providers'):raise ValueError()
        # Reject non-JSON YAML scalars and deep recursive input before transport.
        json.dumps(data,allow_nan=False)
    except (ValueError,TypeError,yaml.YAMLError,RecursionError):raise HTTPException(422,'请提供标准 Clash / Mihomo YAML，包含 proxies 或 proxy-providers；不支持纯节点链接或 Base64 订阅')
    return data


async def download(url):
    try:
        async with asyncio.timeout(25):return await _download(url)
    except TimeoutError:raise HTTPException(504,'订阅下载超时，原配置保持不变，请检查网络后重试')


async def _download(url):
    """Resolve every redirect; pin the validated public IP and preserve TLS SNI."""
    async with httpx.AsyncClient(timeout=25,trust_env=False,follow_redirects=False) as c:
        for _ in range(5):
            try:p=urlsplit(url)
            except ValueError:raise HTTPException(400,'订阅 URL 格式无效')
            if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.fragment:
                raise HTTPException(400,'订阅需要有效的 HTTP(S) URL')
            try:
                addresses=await asyncio.to_thread(socket.getaddrinfo,p.hostname,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM)
                ips=list(dict.fromkeys(x[4][0] for x in addresses))
                # Clash/Mihomo Fake-IP is not a public address. Resolve the hostname
                # independently instead of permitting arbitrary private destinations.
                if ips and all(ipaddress.ip_address(x) in ipaddress.ip_network('198.18.0.0/15') for x in ips):
                    answer=await c.get('https://1.1.1.1/dns-query',params={'name':p.hostname,'type':'A'},headers={'Accept':'application/dns-json'})
                    answer.raise_for_status()
                    ips=[row['data'] for row in answer.json().get('Answer',[]) if row.get('type')==1]
                if not ips or any(not ipaddress.ip_address(x).is_global for x in ips):raise ValueError()
                pinned=httpx.URL(url).copy_with(host=ips[0])
                host=p.hostname+((':'+str(p.port)) if p.port else '')
                async with c.stream('GET',pinned,headers={'Host':host,'User-Agent':'clash.meta/RemoteHub'},extensions={'sni_hostname':p.hostname}) as r:
                    if r.status_code in (301,302,303,307,308):
                        target=urljoin(url,r.headers.get('location',''))
                        if p.scheme=='https' and urlsplit(target).scheme!='https':raise ValueError()
                        url=target;continue
                    if r.status_code!=200:raise HTTPException(502,'订阅服务器返回 HTTP '+str(r.status_code))
                    raw=bytearray()
                    async for chunk in r.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw)>LIMIT:raise HTTPException(413,'订阅配置超过 3 MiB')
                    usage={}
                    for field in r.headers.get('subscription-userinfo','').split(';'):
                        k,_,v=field.strip().partition('=')
                        if k in ('upload','download','total','expire') and v.isdigit():usage[k]=int(v)
                    return raw.decode('utf-8-sig'),usage
            except (ValueError,UnicodeError,socket.gaierror,httpx.HTTPError):raise HTTPException(502,'订阅下载失败，请检查 URL、网络或证书；仅允许公网地址')
    raise HTTPException(502,'订阅重定向过多')


def public(row,active):
    cfg=row['source']
    return dict(id=row['id'],name=row['name'],active=row['id']==active,revision=rev(row),
                subscription=bool(row.get('url')),updated=row['updated'],usage=row.get('usage',{}),
                nodes=len(cfg.get('proxies') or []),groups=len(cfg.get('proxy-groups') or []),rules=len(cfg.get('rules') or []))


@router.get('')
async def status():
    data=library()
    try:engine=await call('GET','/orh/state')
    except HTTPException as e:engine={'ready':False,'error':e.detail,'privileged':False,'enabled':False}
    active=next((x for x in data['profiles'] if x['id']==data['active']),None)
    # A crash between engine commit and library commit must be visible.
    consistent=not active or not engine.get('ready') or engine.get('config_revision')==hashlib.sha256(json.dumps(active['source'],sort_keys=True).encode()).hexdigest()
    from app.main import ROOT
    managed=bool(settings()) and not os.environ.get('ORH_CLASH_SOCKET','').strip() and not os.environ.get('ORH_CLASH_URL','').strip()
    return dict(managed=managed,network_update_required=bool(engine.get('ready') and engine.get('privileged') and engine.get('network_revision',0)<2),engine=engine,profiles=[public(x,data['active']) for x in sorted(data['profiles'],key=lambda x:x['name'].casefold())],consistent=consistent,install_command='sudo '+('/usr/bin/python3' if __import__('sys').platform=='darwin' else 'python3')+' '+shlex.quote(str(ROOT/'scripts/proxy_setup.py'))+' install')


class Import(BaseModel):
    name:str=Field(min_length=1,max_length=120)
    url:str=Field(default='',max_length=4096)
    text:str=Field(default='',max_length=LIMIT)


@router.post('/import')
async def import_profile(body:Import):
    from app.main import audit
    if bool(body.url)==bool(body.text):raise HTTPException(400,'请选择订阅 URL 或 YAML 内容中的一种')
    text,usage=await download(body.url) if body.url else (body.text,{})
    source=parse(text)
    # The same broker normalizer/tester is used for validation without activating.
    await validate(source)
    row=dict(id=uuid.uuid4().hex,name=body.name.strip(),url=body.url,source=source,updated=time.time(),usage=usage)
    if not row['name']:raise HTTPException(400,'请输入配置名称')
    async with lock:
        with disk_lock():
            data=library();data['profiles'].append(row);atomic(root()/'profiles.json',data)
    audit('proxy-profile',row['id'],'import')
    return public(row,data['active'])


async def validate(source):
    # Validation lives in the broker so it uses the installed core and root-owned paths.
    return await call('POST','/orh/validate',{'source':source})


def admin(request):
    if request.state.role!='admin':raise HTTPException(403,'配置文件包含订阅凭据，仅管理员可查看')


@router.get('/profile/{key}')
async def profile(key:str,request:Request):
    admin(request);data=library();row=find(data,key)
    return dict(**public(row,data['active']),text=yaml.safe_dump(row['source'],allow_unicode=True,sort_keys=False))


@router.get('/profile/{key}/download')
async def export_profile(key:str,request:Request):
    admin(request);row=find(library(),key)
    return Response(yaml.safe_dump(row['source'],allow_unicode=True,sort_keys=False),media_type='application/yaml',headers={'Content-Disposition':'attachment; filename="profile.yaml"'})


class Operation(BaseModel):
    action:str
    id:str=Field(default='',max_length=32)
    revision:str=Field(default='',max_length=64)
    confirm:str=Field(default='',max_length=120)
    text:str=Field(default='',max_length=LIMIT)
    name:str=Field(default='',max_length=120)
    url:str=Field(default='',max_length=4096)


@router.post('/profile')
async def operate(body:Operation):
    from app.main import audit
    if body.action not in ('activate','update','save','rename','delete','subscription'):raise HTTPException(400,'不支持的配置操作')
    async with lock:
        with disk_lock():
            data=library();row=find(data,body.id,body.revision)
            if body.action=='delete' and body.confirm!=row['name']:raise HTTPException(400,'请确认配置名称')
            if body.action=='delete':
                if data['active']==row['id']:
                    state=await call('GET','/orh/state')
                    if state['enabled']:raise HTTPException(409,'请先停止代理，再移除当前配置')
                    await call('POST','/orh/control',{'action':'apply','source':{},'revision':state['revision']})
                    data['active']=None
                # Recoverable private copy, never silently destroy credentials.
                trash=root()/'trash';trash.mkdir(mode=0o700,exist_ok=True);atomic(trash/(row['id']+'.json'),row)
                data['profiles'].remove(row)
            elif body.action=='rename':
                if not body.name.strip():raise HTTPException(400,'请输入名称')
                row['name']=body.name.strip()
            elif body.action=='subscription':
                try:p=urlsplit(body.url)
                except ValueError:raise HTTPException(400,'订阅 URL 无效')
                if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:raise HTTPException(400,'订阅 URL 无效')
                row['url']=body.url
            else:
                new=dict(row)
                if body.action=='update':
                    if not row.get('url'):raise HTTPException(400,'此配置没有订阅 URL，请编辑 YAML')
                    text,usage=await download(row['url']);new.update(source=parse(text),usage=usage,updated=time.time())
                elif body.action=='save':new.update(source=parse(body.text),updated=time.time())
                if body.action=='activate' or data['active']==row['id']:
                    state=await call('GET','/orh/state')
                    await call('POST','/orh/control',{'action':'apply','source':new['source'],'revision':state['revision']})
                    data['active']=row['id']
                else:await validate(new['source'])
                row.update(new)
            atomic(root()/'profiles.json',data)
        audit('proxy-profile',body.id,body.action)
    return {'ok':True}


class Service(BaseModel):
    action:str
    revision:str
    confirm:str=''


@router.post('/service')
async def service(body:Service):
    from app.main import audit
    if body.action not in ('enable','disable','restart'):raise HTTPException(400,'不支持的服务操作')
    if body.action in ('disable','restart') and body.confirm!=body.action:raise HTTPException(400,'请确认服务操作')
    async with lock:
        with disk_lock():
            data=library()
            if body.action=='enable' and not data['active']:raise HTTPException(409,'请先导入并选择机场配置')
            if body.action=='enable':
                active=find(data,data['active']);state=await call('GET','/orh/state')
                if state.get('network_revision',0)<2:raise HTTPException(409,'请先更新主机代理服务，以修复 macOS 系统 DNS 接管')
                expected=hashlib.sha256(json.dumps(active['source'],sort_keys=True).encode()).hexdigest()
                if state.get('config_revision')!=expected:raise HTTPException(409,'后台配置已变化，请重新使用所需配置再启动')
            result=await call('POST','/orh/control',{'action':body.action,'revision':body.revision})
        audit('proxy-service','managed',body.action)
    return result


@router.get('/logs')
async def logs():return await call('GET','/orh/logs')


@router.get('/rules')
async def rules():
    result=await call('GET','/rules')
    rows=result.get('rules') or []
    return dict(total=len(rows),entries=[{k:r.get(k) for k in ('type','payload','proxy')} for r in rows[:2000]])


class Close(BaseModel):
    id:str=Field(default='',max_length=80,pattern=r'^[A-Za-z0-9-]*$')
    confirm:str


@router.post('/connections/close')
async def close_connections(body:Close):
    from app.main import audit
    if body.confirm!=(body.id or 'all'):raise HTTPException(400,'请确认要断开的连接')
    await call('DELETE','/connections'+('/'+body.id if body.id else ''))
    audit('proxy-connections',body.id or 'all','close')
    return {'ok':True}
