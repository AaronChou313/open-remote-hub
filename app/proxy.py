"""Scoped Clash/Mihomo control through an existing local controller."""
import asyncio
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import time
from urllib.parse import quote, urlsplit
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.platforms import host

router=APIRouter(prefix='/api/proxy',tags=['proxy'])
control_lock=asyncio.Lock()


def controller():
    from app import proxy_manager
    if not os.environ.get('ORH_CLASH_SOCKET','').strip() and not os.environ.get('ORH_CLASH_URL','').strip() and proxy_manager.settings():return proxy_manager.client()
    socket=os.environ.get('ORH_CLASH_SOCKET','').strip()
    url=os.environ.get('ORH_CLASH_URL','').strip()
    default=Path.home()/'Library/Group Containers/group.com.hako.network/clash.sock'
    if not socket and not url and default.exists():socket=str(default)
    if socket:
        path=Path(socket).expanduser()
        if not path.is_absolute():raise HTTPException(503,'ORH_CLASH_SOCKET 需要绝对路径')
        return httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(path)),base_url='http://localhost',timeout=4,trust_env=False)
    url=url or 'http://127.0.0.1:9090'
    try:
        parsed=urlsplit(url)
        if parsed.scheme not in ('http','https') or not ipaddress.ip_address(parsed.hostname).is_loopback or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment or not parsed.port:raise ValueError()
    except (ValueError,TypeError):raise HTTPException(503,'ORH_CLASH_URL 需要带端口的本机回环 HTTP(S) 地址')
    secret=os.environ.get('ORH_CLASH_SECRET','')
    return httpx.AsyncClient(base_url=url,headers={'Authorization':'Bearer '+secret} if secret else {},timeout=4,trust_env=False)


async def request(client,method,path,**kwargs):
    try:
        async with client.stream(method,path,**kwargs) as response:
            if response.status_code in (401,403):raise HTTPException(503,'Clash 控制器拒绝访问，请检查本机控制器密钥或 Socket 权限')
            if response.status_code>=400:raise HTTPException(502,'Clash 拒绝了此操作（HTTP '+str(response.status_code)+'）')
            raw=bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw)>8*1024**2:raise HTTPException(413,'Clash 返回的数据过大，请在原客户端缩小查看范围')
            value=json.loads(raw) if raw else {}
            if not isinstance(value,dict):raise ValueError()
            return value
    except httpx.HTTPError as e:raise HTTPException(503,'无法连接本机 Clash 控制器，请检查 Clash 是否连接及控制器配置') from e
    except (ValueError,TypeError) as e:raise HTTPException(502,'Clash 控制器返回格式异常') from e


def revision(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def group_revision(group):return revision([group.get('type'),group.get('now'),group.get('all')])


@router.get('')
async def status():
    try:system=await asyncio.to_thread(host.proxy_status)
    except RuntimeError:system=dict(proxies=[],vpn=None,note='系统代理状态暂时无法读取')
    try:
        async with controller() as client:
            results=await asyncio.gather(*[request(client,'GET',path) for path in ('/version','/configs','/proxies','/connections')],return_exceptions=True)
            for result in results:
                if isinstance(result,Exception):raise result
            version,config,proxies,connections=results
    except HTTPException as e:
        return dict(available=False,error=e.detail,system=system)
    nodes=proxies.get('proxies',{})
    groups=[]
    for name,group in nodes.items():
        if not isinstance(group.get('all'),list):continue
        groups.append(dict(name=name,type=group.get('type'),current=group.get('now',''),members=group['all'],selectable=group.get('type')=='Selector',revision=group_revision(group)))
    groups.sort(key=lambda group:group['name'].casefold())
    return dict(available=True,version=version.get('version'),mode=config.get('mode'),revision=revision(config.get('mode')),tun_enabled=config.get('tun',{}).get('enable'),system=system,groups=groups,node_count=len(nodes),connection_count=len(connections.get('connections') or []),memory=connections.get('memory'),upload_total=connections.get('uploadTotal'),download_total=connections.get('downloadTotal'),time=time.time())


@router.get('/connections')
async def connections():
    async with controller() as client:data=await request(client,'GET','/connections')
    rows=data.get('connections') or []
    rows.sort(key=lambda row:row.get('download',0)+row.get('upload',0),reverse=True)
    result=[]
    for row in rows[:50]:
        meta=row.get('metadata') or {}
        result.append(dict(id=row.get('id'),host=meta.get('host') or meta.get('destinationIP'),port=meta.get('destinationPort'),network=meta.get('network'),process=meta.get('process'),chains=row.get('chains') or [],rule=row.get('rule'),upload=row.get('upload'),download=row.get('download')))
    return dict(entries=result,total=len(rows))


class Control(BaseModel):
    action:str
    target:str=Field(default='',max_length=1024)
    value:str=Field(max_length=1024)
    revision:str
    confirm:str


@router.post('/control')
async def control(body:Control):
    from app.main import audit
    if body.action not in ('mode','select'):raise HTTPException(400,'不支持的代理操作')
    target='mode' if body.action=='mode' else body.target
    if not target or body.confirm!=target:raise HTTPException(400,'请确认代理操作的具体目标')
    async with control_lock:
        async with controller() as client:
            if body.action=='mode':
                if body.value not in ('rule','global','direct'):raise HTTPException(400,'代理模式无效')
                current=await request(client,'GET','/configs')
                if revision(current.get('mode'))!=body.revision:raise HTTPException(409,'Clash 模式已变更，请刷新后重试')
                await request(client,'PATCH','/configs',json={'mode':body.value})
                audit('proxy',target,body.action)
                latest=await request(client,'GET','/configs')
                applied=latest.get('mode')==body.value
            else:
                proxies=(await request(client,'GET','/proxies')).get('proxies',{})
                group=proxies.get(target)
                if not group or group.get('type')!='Selector' or body.value not in group.get('all',[]):raise HTTPException(400,'请选择现有手动策略组中的节点')
                if group_revision(group)!=body.revision:raise HTTPException(409,'策略组已变更，请刷新后重试')
                path='/proxies/'+quote(target,safe='')
                await request(client,'PUT',path,json={'name':body.value})
                audit('proxy',target,body.action)
                latest=await request(client,'GET',path)
                applied=latest.get('now')==body.value
    if not applied:raise HTTPException(409,'Clash 已接受请求，但当前状态与目标不同，请刷新检查')
    return dict(ok=True)


class Delay(BaseModel):
    name:str=Field(min_length=1,max_length=1024)


@router.post('/delay')
async def delay(body:Delay):
    async with controller() as client:
        nodes=(await request(client,'GET','/proxies')).get('proxies',{})
        if body.name not in nodes:raise HTTPException(404,'代理节点不存在，请刷新')
        data=await request(client,'GET','/proxies/'+quote(body.name,safe='')+'/delay',params={'url':'https://www.gstatic.com/generate_204','timeout':'4000'},timeout=6)
    return dict(name=body.name,delay=data.get('delay'))
