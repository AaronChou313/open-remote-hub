"""Authenticated gateway to the loopback-only Zellij Web Client.

The upstream token and session cookie never leave this process. Browser cookies
are scoped to RemoteHub; upstream Set-Cookie and request credentials are stripped.
"""
import asyncio
import json
import os
import re
from urllib.parse import urlencode

import httpx
import websockets
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, Response, FileResponse
from app import access

router = APIRouter()


class Upstream:
    def __init__(self):
        self.client = None
        self.lock = asyncio.Lock()

    def base(self):
        from app import main
        return f'http://127.0.0.1:{main.ZPORT}'

    async def close(self):
        if self.client:
            await self.client.aclose()
            self.client = None

    async def authenticate(self, force=False):
        from app import main
        async with self.lock:
            if self.client and self.client.cookies and not force:
                return self.client
            if not self.client:
                self.client = httpx.AsyncClient(base_url=self.base(), timeout=15, trust_env=False)
            p = main.DATA / 'zellij-gateway.json'
            if p.exists():
                token = json.loads(p.read_text())['token']
            else:
                out = await asyncio.to_thread(main.command, ['zellij', 'web', '--create-token'])
                match = re.search(r'^([^\s:]+):\s+(\S+)\s*$', out, re.M)
                if not match:
                    raise RuntimeError('无法创建 Zellij 内部认证凭据')
                token = match[2]
                fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, 'w') as f:
                    json.dump({'name': match[1], 'token': token}, f)
            r = await self.client.post('/command/login', json={'auth_token': token, 'remember_me': True})
            if r.status_code != 200:
                raise RuntimeError('Zellij 内部认证失败，请检查本机 Web 服务和网关凭据')
            return self.client

    async def request(self, method, path, query):
        client = await self.authenticate()
        r = await client.request(method, path, params=query)
        if r.status_code == 401:
            client = await self.authenticate(force=True)
            r = await client.request(method, path, params=query)
        return r


upstream = Upstream()


def admin(cookie):
    from app import passwords
    s = access.get(cookie)
    return bool(passwords.record() and s and s['role'] == 'admin')


def route_allowed(path, method):
    from app import main
    if method == 'GET' and (re.fullmatch(r'assets/[A-Za-z0-9_.-]+', path) or path in ('info/version', 'session-list', '')):
        return True
    if method == 'POST':
        return path == 'session'
    if method == 'GET':
        try:
            main.zname(path)
            return True
        except HTTPException:
            pass
    return False


@router.get('/terminal')
def terminal_root():
    return RedirectResponse('/terminal/')


@router.get('/terminal/open/{name}')
async def entry_page(request:Request,name:str):
    from app import main
    main.zname(name)
    # The launcher can explain login expiry and resume after login in another tab.
    return FileResponse(main.ROOT/'static/terminal-entry.html')


@router.post('/api/zellij/{name}/enter')
async def enter(request:Request,name:str):
    if not admin(request.cookies.get('orh','')):
        raise HTTPException(403,'请先登录控制台')
    from app.ssh.security import protect_session
    protect_session(request, name)
    from app.terminal_entry import prepare
    return await asyncio.to_thread(prepare,name)


@router.api_route('/terminal/{path:path}', methods=['GET', 'POST'])
async def native(request: Request, path: str):
    if not admin(request.cookies.get('orh', '')):
        if request.method == 'GET' and (not path or '/' not in path):
            return HTMLResponse('<!doctype html><meta charset="utf-8"><title>请登录 RemoteHub</title><p>登录已到期，请<a href="/" target="_blank" rel="noopener">返回控制台登录</a>后刷新此页。</p>', status_code=403)
        raise HTTPException(403, '请先登录 RemoteHub，再刷新终端页面')
    from app.ssh.security import protect_session
    protect_session(request, path.split('/')[0])
    if not route_allowed(path, request.method):
        raise HTTPException(404)
    # The native session endpoint must attach an explicitly selected live session.
    query = list(request.query_params.multi_items())
    if request.method == 'POST':
        from app import main
        name = request.query_params.get('session', '')
        main.zname(name)
        entries = await asyncio.to_thread(main.zellij_list)
        if not any(s['name'] == name and s['status'] == 'running' for s in entries['sessions']):
            raise HTTPException(409, '请在控制台创建或恢复会话后进入')
    try:
        r = await upstream.request(request.method, '/' + path, query)
    except (httpx.HTTPError, RuntimeError):
        raise HTTPException(503, 'Zellij Web 服务不可用，请在控制台启动本地 Web 服务后重试')
    if r.status_code == 401:
        raise HTTPException(503, 'Zellij 内部认证失效，请检查本机服务')
    content=r.content
    if r.status_code==200:
        from app.terminal_browser import client_asset,client_page
        if path=='assets/app.js':content=client_asset(content)[0]
        elif 'text/html' in r.headers.get('content-type',''):
            script=await upstream.request('GET','/assets/app.js',[])
            if script.status_code!=200:raise HTTPException(503,'Zellij 客户端资源不可用')
            content=client_page(content,script.content)
    return Response(content, status_code=r.status_code,
                    headers={'Content-Type': r.headers.get('content-type', 'application/octet-stream')})


def native_connection(url,cookie):
    # Zellij 0.45.1 logs protocol Ping as unsupported. Match native browser
    # behavior instead of injecting automatic upstream heartbeat frames.
    return websockets.connect(url,origin=upstream.base(),additional_headers={'Cookie':cookie},
                              max_size=4*1024*1024,proxy=None,ping_interval=None,close_timeout=2)


connections = {}


@router.websocket('/terminal/ws/{path:path}')
async def native_socket(ws: WebSocket, path: str):
    from app import main
    token = ws.cookies.get('orh', '')
    authority = f'{ws.headers.get("host")}'
    scheme='https' if ws.url.scheme=='wss' else 'http'
    if not main.NETWORK.same_origin(authority,ws.headers.get('origin'),main.PORT,scheme) or not admin(token):
        await ws.close(code=1008)
        return
    if path != 'control' and not path.startswith('terminal/'):
        await ws.close(code=1008)
        return
    if path.startswith('terminal/'):
        try:
            main.zname(path[len('terminal/'):])
            from app.ssh.security import protect_session
            protect_session(ws, path[len('terminal/'):])
        except HTTPException:
            await ws.close(code=1008)
            return
    if len(connections) >= 32 or sum(t == token for t in connections.values()) >= 16:
        await ws.close(code=1013)
        return
    connections[id(ws)] = token
    accepted = False
    tasks = []
    try:
        client = await upstream.authenticate()
        cookie = '; '.join(f'{k}={v}' for k, v in client.cookies.items())
        url = upstream.base().replace('http:', 'ws:') + '/ws/' + path
        ids = ws.query_params.get('web_client_id', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', ids):
            await ws.close(code=1008)
            return
        query = {'web_client_id': ids}
        if path.startswith('terminal/'):
            for field, low, high in [('rows',1,500),('cols',1,1000),('cell_width',1,100),('cell_height',1,200)]:
                value=ws.query_params.get(field)
                if value is not None:
                    if not value.isdecimal() or not low <= int(value) <= high:
                        await ws.close(code=1008)
                        return
                    query[field]=value
            if 'rows' not in query or 'cols' not in query:
                await ws.close(code=1008)
                return
        url += '?' + urlencode(query)
        async with native_connection(url,cookie) as backend:
            await ws.accept()
            accepted = True
            async def browser_to_native():
                while True:
                    message = await ws.receive()
                    if message['type'] == 'websocket.disconnect' or not admin(token):
                        return
                    data = message.get('bytes') if message.get('bytes') is not None else message.get('text')
                    if data is not None:
                        await backend.send(data)
            async def native_to_browser():
                async for data in backend:
                    if isinstance(data, bytes):
                        await ws.send_bytes(data)
                    else:
                        await ws.send_text(data)
            async def check_login():
                while True:
                    await asyncio.sleep(2)
                    if not admin(token):
                        return
            tasks = [asyncio.create_task(f()) for f in (browser_to_native, native_to_browser, check_login)]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except (OSError, RuntimeError, websockets.WebSocketException, httpx.HTTPError):
        pass
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        connections.pop(id(ws), None)
        try:
            await ws.close(code=1000 if accepted else 1013)
        except (RuntimeError, WebSocketDisconnect):
            pass
