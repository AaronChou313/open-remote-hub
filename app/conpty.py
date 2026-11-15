"""Agent-owned Windows ConPTY sessions with reconnectable output."""
import asyncio
from collections import deque
import json
import os
from pathlib import Path
import shutil
import threading
import time

from fastapi import APIRouter, HTTPException, WebSocket
from fastapi.responses import FileResponse

router = APIRouter()
lock = threading.RLock()
sessions = {}


class Session:
    def __init__(self, name, process):
        self.name = name
        self.process = process
        self.created = time.time()
        self.output = deque()
        self.output_size = 0
        self.listeners = set()
        self.closed = False
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        try:
            while True:
                data = self.process.read(32768)
                if not data:
                    break
                with lock:
                    self.output.append(data)
                    self.output_size += len(data)
                    while self.output_size > 1024 * 1024 and len(self.output) > 1:
                        self.output_size -= len(self.output.popleft())
                    for loop, queue in list(self.listeners):
                        loop.call_soon_threadsafe(queue.put_nowait, data)
        except (EOFError, OSError):
            pass
        finally:
            with lock:
                self.closed = True
                for loop, queue in list(self.listeners):
                    loop.call_soon_threadsafe(queue.put_nowait, None)


def prepare(name, cwd=None):
    from app.main import zname
    zname(name)
    with lock:
        current = sessions.get(name)
        if current and not current.closed and current.process.isalive():
            return dict(url='/terminal/conpty/' + name, session=name, state='reused')
        try:
            from winpty import PtyProcess
        except ImportError:
            raise HTTPException(503, '缺少 ConPTY 后端，请重新安装 ORH 或安装 pywinpty') from None
        shell = shutil.which('pwsh') or shutil.which('powershell') or os.environ.get('COMSPEC', 'cmd.exe')
        arguments = [shell, '-NoLogo'] if 'powershell' in shell.lower() or Path(shell).stem.lower() == 'pwsh' else [shell]
        try:
            process = PtyProcess.spawn(arguments, cwd=str(cwd or Path.home()), dimensions=(24, 100), backend=1)
        except (OSError, RuntimeError) as error:
            raise HTTPException(503, 'ConPTY 启动失败：' + str(error)) from None
        sessions[name] = Session(name, process)
    return dict(url='/terminal/conpty/' + name, session=name, state='created')


def listing():
    with lock:
        rows = [dict(name=name, status='exited' if session.closed else 'running',
                     pid=session.process.pid, created=session.created, detail='ConPTY / PowerShell')
                for name, session in sessions.items()]
    return dict(sessions=rows, warning='', backend='conpty')


def mutate(name, action, new_name=''):
    from app.main import zname
    zname(name)
    if action == 'create':
        return prepare(name)
    with lock:
        session = sessions.get(name)
        if not session:
            if action in ('delete', 'purge'):
                return dict(output='会话已删除')
            raise HTTPException(404, '会话不存在')
        if action == 'rename':
            zname(new_name)
            if new_name != name and new_name in sessions:
                raise HTTPException(409, '会话名称已存在')
            sessions.pop(name)
            session.name = new_name
            sessions[new_name] = session
        elif action in ('kill', 'purge'):
            if not session.closed:
                session.process.close(force=True)
            session.closed = True
            if action == 'purge':
                sessions.pop(name)
        elif action == 'delete':
            if not session.closed:
                raise HTTPException(409, '请先结束会话')
            sessions.pop(name)
        else:
            raise HTTPException(400, '不支持的终端操作')
    return dict(output='操作完成')


@router.get('/terminal/conpty/{name}')
def page(name: str):
    from app.main import ROOT, zname
    zname(name)
    return FileResponse(ROOT / 'static/conpty.html')


@router.websocket('/terminal/conpty-ws/{name}')
async def socket(ws: WebSocket, name: str):
    from app import main, modules
    from app.native_terminal import admin
    token = ws.cookies.get('orh', '')
    scheme = 'https' if ws.url.scheme == 'wss' else 'http'
    if (not modules.enabled('terminal') or not admin(token)
            or not main.NETWORK.same_origin(ws.headers.get('host', ''), ws.headers.get('origin'), main.PORT, scheme)):
        await ws.close(code=1008)
        return
    with lock:
        session = sessions.get(name)
        if not session:
            await ws.close(code=1008)
            return
        queue = asyncio.Queue()
        listener = (asyncio.get_running_loop(), queue)
        session.listeners.add(listener)
        history = ''.join(session.output)
        if session.closed:
            queue.put_nowait(None)
    await ws.accept()
    await ws.send_text(history)

    async def send():
        while True:
            data = await queue.get()
            if data is None:
                await ws.send_text('\r\n[会话已结束]\r\n')
                return
            await ws.send_text(data)

    async def receive():
        while True:
            message = json.loads(await ws.receive_text())
            if message.get('type') == 'input':
                await asyncio.to_thread(session.process.write, str(message.get('data', '')))
            elif message.get('type') == 'resize':
                rows, cols = int(message['rows']), int(message['cols'])
                if 1 <= rows <= 500 and 1 <= cols <= 1000:
                    await asyncio.to_thread(session.process.setwinsize, rows, cols)

    async def check_login():
        while admin(token) and modules.enabled('terminal'):
            await asyncio.sleep(2)

    tasks = [asyncio.create_task(send()), asyncio.create_task(receive()), asyncio.create_task(check_login())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        with lock:
            session.listeners.discard(listener)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if ws.client_state.name != 'DISCONNECTED':
            await ws.close()
