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
delay_lock=asyncio.Semaphore(4)
SELECTABLE=('Selector','URLTest','Fallback')


def managed_controller():
    from app import proxy_manager
    return not os.environ.get('ORH_CLASH_SOCKET','').strip() and not os.environ.get('ORH_CLASH_URL','').strip() and bool(proxy_manager.settings())


def controller():
    from app import proxy_manager
    if managed_controller():return proxy_manager.client()
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


def group_revision(group):return revision([group.get('type'),group.get('now'),group.get('all'),group.get('fixed')])


@router.get('')
async def status():
    try:system=await asyncio.to_thread(host.proxy_status)
    except RuntimeError:system=dict(proxies=[],vpn=None,note='系统代理状态暂时无法读取')
    try:
        async with controller() as client:
            managed=managed_controller()
            paths=['/version','/configs','/proxies','/connections','/rules']+(['/orh/state'] if managed else [])
            results=await asyncio.gather(*[request(client,'GET',path) for path in paths],return_exceptions=True)
            for result in results[:4]:
                if isinstance(result,Exception):raise result
            version,config,proxies,connections,rules=results[:5]
            if not isinstance(rules,dict):rules={}
            config_revision=results[5].get('config_revision') if managed and isinstance(results[5],dict) else None
    except HTTPException as e:
        return dict(available=False,error=e.detail,system=system)
    nodes=proxies.get('proxies',{})
    groups=[]
    for name,group in nodes.items():
        if not isinstance(group.get('all'),list):continue
        groups.append(dict(name=name,type=group.get('type'),current=group.get('now',''),fixed=group.get('fixed',''),members=group['all'],selectable=group.get('type') in SELECTABLE,revision=group_revision(group)))
    meta={}
    for name,node in nodes.items():
        history=node.get('history') or []
        last=history[-1] if history and isinstance(history[-1],dict) else {}
        meta[name]=dict(type=node.get('type'),delay=last.get('delay'),tested=bool(history),time=last.get('time'))
    default=next((r.get('proxy') for r in reversed(rules.get('rules') or []) if r.get('type')=='Match'),None)
    return dict(available=True,config_revision=config_revision,version=version.get('version'),mode=config.get('mode'),revision=revision(config.get('mode')),tun_enabled=config.get('tun',{}).get('enable'),dns_mode=config.get('tun',{}).get('dns-mode'),system=system,groups=groups,nodes=meta,default_policy=default,node_count=len(nodes),connection_count=len(connections.get('connections') or []),memory=connections.get('memory'),upload_total=connections.get('uploadTotal'),download_total=connections.get('downloadTotal'),time=time.time())


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
    value:str=Field(default='',max_length=1024)
    revision:str
    confirm:str=''
    profile_revision:str|None=Field(default=None,max_length=64)


@router.post('/control')
async def control(body:Control):
    from app.main import audit
    if body.action not in ('mode','select','unfix'):raise HTTPException(400,'不支持的代理操作')
    target='mode' if body.action=='mode' else body.target
    if not target:raise HTTPException(400,'请选择策略组')
    from app import proxy_manager
    async with control_lock,proxy_manager.lock:
        async with controller() as client:
            if managed_controller():
                state=await request(client,'GET','/orh/state')
                if state.get('config_revision')!=body.profile_revision:raise HTTPException(409,'机场配置已变化，请刷新后重试')
            if body.action=='mode':
                if body.value not in ('rule','global','direct'):raise HTTPException(400,'代理模式无效')
                current=await request(client,'GET','/configs')
                if revision(current.get('mode'))!=body.revision:raise HTTPException(409,'Clash 模式已变更，请刷新后重试')
                await request(client,'PATCH','/configs',json={'mode':body.value})
                audit('proxy',target,body.action)
                latest=await request(client,'GET','/configs')
                applied=latest.get('mode')==body.value
                result=dict(mode=latest.get('mode'),revision=revision(latest.get('mode')))
            else:
                proxies=(await request(client,'GET','/proxies')).get('proxies',{})
                group=proxies.get(target)
                if not group or group.get('type') not in SELECTABLE:raise HTTPException(400,'此策略组不支持手动选择')
                if body.action=='unfix':
                    if group.get('type')=='Selector':raise HTTPException(400,'此策略组没有自动选择模式')
                elif body.value not in group.get('all',[]):raise HTTPException(400,'请选择策略组中已有的节点')
                if group_revision(group)!=body.revision:raise HTTPException(409,'策略组已变更，请刷新后重试')
                path='/proxies/'+quote(target,safe='')
                if body.action=='unfix':await request(client,'DELETE',path)
                else:await request(client,'PUT',path,json={'name':body.value})
                audit('proxy',target,body.action)
                latest=await request(client,'GET',path)
                applied=not latest.get('fixed') if body.action=='unfix' else latest.get('now')==body.value or latest.get('fixed')==body.value
                result=dict(current=latest.get('now',''),fixed=latest.get('fixed',''),revision=group_revision(latest))
    if not applied:raise HTTPException(409,'Clash 已接受请求，但当前状态与目标不同，请刷新检查')
    return dict(ok=True,**result)


class Delay(BaseModel):
    name:str=Field(min_length=1,max_length=1024)


@router.post('/delay')
async def delay(body:Delay):
    async with delay_lock:
        async with controller() as client:
            nodes=(await request(client,'GET','/proxies')).get('proxies',{})
            if body.name not in nodes:raise HTTPException(404,'代理节点不存在，请刷新')
            try:data=await request(client,'GET','/proxies/'+quote(body.name,safe='')+'/delay',params={'url':'https://www.gstatic.com/generate_204','timeout':'4000'},timeout=6)
            except HTTPException as e:
                if e.status_code not in (502,503):raise
                return dict(name=body.name,delay=None,error='超时或不可达',time=time.time())
    return dict(name=body.name,delay=data.get('delay'),time=time.time())
