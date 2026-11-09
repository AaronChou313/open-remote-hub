"""Origin-isolated authenticated carrier for the unmodified official DSH Web UI."""
import asyncio
import html
import re
from urllib.parse import urlsplit
import httpx
import websockets
from fastapi import FastAPI, Request, WebSocket, HTTPException, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from app import access
from app.dsh import settings

app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
client=None
connections={}


def base():return f"http://127.0.0.1:{settings()['port']}"


def authorized(token):
    s=access.get(token)
    return bool(s and s['role']=='admin')


def console_origin(scheme,authority):
    from app import main
    hostname=urlsplit(scheme+'://'+authority).hostname
    return f'{scheme}://{f"[{hostname}]" if ":" in hostname else hostname}:{main.PORT}'


def valid_path(path):return len(path)<8192 and '\\' not in path and '\x00' not in path and not any(x in ('.','..') for x in path.split('/'))


async def close():
    global client
    if client:await client.aclose();client=None


@app.api_route('/{path:path}',methods=['GET','HEAD','POST','PUT','PATCH','DELETE','OPTIONS'])
async def native(request:Request,path:str):
    from app import main
    global client
    cfg=settings();authority=request.headers.get('host','');scheme=request.url.scheme
    if not cfg['enabled'] or not main.NETWORK.allows(authority,cfg['gateway_port'],scheme):raise HTTPException(400,'Invalid DSH host')
    origin=request.headers.get('origin')
    if (origin and not main.NETWORK.same_origin(authority,origin,cfg['gateway_port'],scheme)) or request.headers.get('sec-fetch-site')=='cross-site':raise HTTPException(403,'DSH cross-origin request denied')
    if request.method not in ('GET','HEAD') and not main.NETWORK.same_origin(authority,origin,cfg['gateway_port'],scheme):raise HTTPException(403,'DSH origin required')
    token=request.cookies.get('orh','')
    if not authorized(token):
        if request.method=='GET' and path in ('','index.html'):
            url=html.escape(console_origin(scheme,authority),quote=True)
            return HTMLResponse(f'<!doctype html><meta charset="utf-8"><title>请登录 RemoteHub</title><p>请先<a href="{url}/" target="_top">登录 RemoteHub</a>，再进入 DSH。</p>',status_code=401)
        raise HTTPException(401,'请登录 RemoteHub')
    if not valid_path(path):raise HTTPException(400,'Invalid path')
    if path=='__remotehub__/compat.js':
        return Response((main.ROOT/'static/dsh-compat.js').read_bytes(),media_type='application/javascript',headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
    if client is None:client=httpx.AsyncClient(trust_env=False,timeout=httpx.Timeout(30,read=None),follow_redirects=False)
    # Client cookies, Authorization, Host and forwarding headers never reach DSH.
    headers={k:v for k,v in request.headers.items() if k.lower() in ('content-type','range','accept','if-none-match')}
    from app.dsh import native_cookie
    headers.update({'Origin':base(),'Accept-Encoding':'identity','Cookie':await asyncio.to_thread(native_cookie)})
    target=base()+'/'+path
    if request.url.query:target+='?'+request.url.query
    try:r=await client.send(client.build_request(request.method,target,headers=headers,content=request.stream() if request.method not in ('GET','HEAD') else None),stream=True)
    except httpx.HTTPError:raise HTTPException(503,'DSH Web 服务不可用，请返回控制台重试连接')
    if r.status_code==401:
        await r.aclose();raise HTTPException(503,'DSH 本机认证暂不可用，请返回控制台重试连接')
    response_headers={k:v for k,v in r.headers.items() if k.lower() in ('content-type','content-length','content-range','accept-ranges','etag','content-encoding','content-disposition')}
    location=r.headers.get('location')
    if location:
        parsed=urlsplit(location)
        if parsed.netloc==urlsplit(base()).netloc:
            location=f'{scheme}://{authority}'+parsed.path+('?' + parsed.query if parsed.query else '')
        if not location.lower().startswith(('javascript:','data:')):response_headers['Location']=location
    response_headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Content-Security-Policy':f"frame-ancestors 'self' {console_origin(scheme,authority)}; object-src 'none'; base-uri 'self'"})
    if 'text/html' in r.headers.get('content-type',''):
        try:
            body=await r.aread()
            if len(body)>4*1024*1024:raise HTTPException(502,'DSH index exceeds gateway limit')
            body=re.sub(rb'(<head\b[^>]*>)',rb'\1<script src="/__remotehub__/compat.js"></script>',body,count=1,flags=re.I)
            for name in ('content-length','content-encoding','etag'):response_headers.pop(name,None)
            return Response(body,status_code=r.status_code,headers=response_headers)
        finally:await r.aclose()
    async def chunks():
        try:
            async for data in r.aiter_raw():
                if not authorized(token):return
                yield data
        except httpx.HTTPError:return
        finally:await r.aclose()
    return StreamingResponse(chunks(),status_code=r.status_code,headers=response_headers)


@app.websocket('/{path:path}')
async def socket(ws:WebSocket,path:str):
    from app import main
    cfg=settings();authority=ws.headers.get('host','');scheme='https' if ws.url.scheme=='wss' else 'http';token=ws.cookies.get('orh','')
    if not cfg['enabled'] or not main.NETWORK.same_origin(authority,ws.headers.get('origin'),cfg['gateway_port'],scheme) or not authorized(token):await ws.close(code=1008);return
    if path!='api/remote.mux':await ws.close(code=1008);return
    if len(connections)>=32:await ws.close(code=1013);return
    connections[id(ws)]=token;tasks=[];accepted=False
    try:
        target=base().replace('http:','ws:')+'/'+path+('?' + ws.url.query if ws.url.query else '')
        from app.dsh import native_cookie
        async with websockets.connect(target,origin=base(),additional_headers={'Cookie':await asyncio.to_thread(native_cookie)},proxy=None,ping_interval=None,max_size=32*1024*1024,close_timeout=2) as backend:
            await ws.accept();accepted=True
            async def incoming():
                while authorized(token):
                    message=await ws.receive()
                    if message['type']=='websocket.disconnect' or not authorized(token):return
                    data=message.get('bytes') if message.get('bytes') is not None else message.get('text')
                    if data is not None:await backend.send(data)
            async def outgoing():
                async for data in backend:
                    if not authorized(token):return
                    if isinstance(data,bytes):await ws.send_bytes(data)
                    else:await ws.send_text(data)
            async def check():
                while authorized(token):await asyncio.sleep(2)
            tasks=[asyncio.create_task(f()) for f in (incoming,outgoing,check)]
            await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            # Close the browser before waiting on the upstream close handshake.
            await ws.close(code=1008 if not authorized(token) else 1000)
    except (OSError,RuntimeError,websockets.WebSocketException):pass
    finally:
        for t in tasks:t.cancel()
        await asyncio.gather(*tasks,return_exceptions=True);connections.pop(id(ws),None)
        try:await ws.close(code=(1008 if not authorized(token) else 1000) if accepted else 1013)
        except (RuntimeError,WebSocketDisconnect):pass


class Dispatch:
    """Socket address selects the application; untrusted Host never selects it."""
    def __init__(self,console,gateway_port):self.console=console;self.gateway_port=gateway_port
    async def __call__(self,scope,receive,send):
        target=app if scope['type']!='lifespan' and (scope.get('server') or ('',0))[1]==self.gateway_port else self.console
        await target(scope,receive,send)
