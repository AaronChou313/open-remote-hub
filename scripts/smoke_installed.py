"""Exercise a fresh installed Agent through its normal authenticated APIs."""
import asyncio
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import sys
import urllib.request

BASE = os.environ.get('ORH_TEST_URL', 'http://127.0.0.1:8765')
cookies = http.cookiejar.CookieJar()
http = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(cookies))


def request(path, value=None, data=None, headers=None):
    raw = json.dumps(value).encode() if value is not None else data
    options = {'Origin':BASE, 'X-ORH-Request':'1', **(headers or {})}
    if value is not None:
        options['Content-Type'] = 'application/json'
    with http.open(urllib.request.Request(BASE + path, data=raw, headers=options), timeout=45) as response:
        content = response.read()
        return json.loads(content) if 'json' in response.headers.get('Content-Type','') else content


async def terminal_socket(name):
    import websockets
    cookie = '; '.join(item.name + '=' + item.value for item in cookies)
    address = BASE.replace('http:', 'ws:') + '/terminal/conpty-ws/' + name
    async with websockets.connect(address, origin=BASE, additional_headers={'Cookie':cookie}, proxy=None) as socket:
        await socket.recv()
        await socket.send(json.dumps(dict(type='resize', rows=28, cols=100)))
        await socket.send(json.dumps(dict(type='input', data="Write-Output ('ORH_' + 'PACKAGE_OK')\r")))
        output = ''
        while 'ORH_PACKAGE_OK' not in output:
            output += await asyncio.wait_for(socket.recv(), 15)
    async with websockets.connect(address, origin=BASE, additional_headers={'Cookie':cookie}, proxy=None) as socket:
        assert 'ORH_PACKAGE_OK' in await asyncio.wait_for(socket.recv(), 15)


def main():
    status = request('/api/auth/status')
    assert status['needs_setup'], 'Use this smoke check on a fresh test installation'
    assert status['version'] == (Path(__file__).resolve().parents[1] / 'VERSION').read_text().strip()
    request('/api/auth/setup', dict(password=secrets.token_urlsafe(24)))
    modules = request('/api/modules')['modules']
    assert {module['id'] for module in modules if module['enabled']}=={'terminal','files','services'}
    request('/api/modules/files/enable', {})
    directory = request('/api/files/roots')['roots'][0]
    root = directory['id']
    name = 'orh-package-' + secrets.token_hex(6) + '.txt'
    entry = request('/api/files/upload?root=' + root + '&path=' + name, data=b'package-file-ok')
    assert request('/api/files/text?root=' + root + '&path=' + name)['text'] == 'package-file-ok'
    assert request('/api/files/download?root=' + root + '&path=' + name, headers={'Range':'bytes=0-6'}) == b'package'
    request('/api/files/operation', dict(root=root, path=name, revision=entry['revision'], action='delete', confirm=name))
    trashed = next(entry for entry in request('/api/files/trash?root=' + root)['entries'] if entry['original_name'] == name)
    request('/api/files/restore', dict(root=root, name=trashed['name'], revision=trashed['revision'], confirm=name))
    (Path(directory['path']) / name).unlink()
    request('/api/modules/services/enable', {})
    task = request('/api/tasks', dict(name='ORH package check', argv=[sys.executable, '-c', 'import time; time.sleep(60)'], cwd=directory['path']))['id']
    request('/api/tasks/' + task, dict(action='start', confirm=task))
    assert any(value['id'] == task and value['running'] for value in request('/api/tasks'))
    request('/api/tasks/' + task, dict(action='stop', confirm=task))
    request('/api/tasks/' + task, dict(action='delete', confirm=task))
    if os.name == 'nt':
        module = request('/api/modules/terminal/enable', {})
        assert module['state'] == 'ready', module
        session = 'orh-package-smoke'
        request('/api/zellij/' + session + '/enter', {})
        assert any(value['name'] == session for value in request('/api/zellij')['sessions'])
        asyncio.run(terminal_socket(session))
        request('/api/zellij/' + session, dict(action='purge', confirm=session))
    print('Installed Agent passed core, module, file transfer and platform terminal checks')


if __name__ == '__main__':
    main()
