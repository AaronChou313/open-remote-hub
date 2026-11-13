"""Local NodeBabyLink 4.5.3 status adapter. Native settings stay with its client."""
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import build_opener, ProxyHandler

APP = Path('/Applications/节点小宝.app')
http = build_opener(ProxyHandler({}))


class NodeBabyError(RuntimeError):
    pass


def request(path, transport=False):
    port = int(os.environ.get('ORH_NODEBABY_LINK_PORT' if transport else 'ORH_NODEBABY_API_PORT',
                              '16880' if transport else '2080'))
    try:
        with http.open(f'http://127.0.0.1:{port}{path}', timeout=1.5) as response:
            return json.load(response)
    except (OSError, URLError, ValueError):
        raise NodeBabyError('节点小宝本地接口暂不可用，请检查客户端与后台服务') from None


def status():
    result = dict(available=APP.exists() or Path('/usr/local/nblink/NodeBabyLinkService').exists(),
                  ready=False, connected=False, tun_ready=False, mappings=[], addresses=[],
                  can_open=sys.platform == 'darwin' and APP.exists())
    try:
        info = request('/detect/version')
        if not isinstance(info, dict) or info.get('name') != 'NodeBabyLinkService':
            raise NodeBabyError('本地端口返回了其他服务，请核对节点小宝 API 端口')
        result.update(available=True, ready=True, version=info.get('version'), pid=info.get('pid'),
                      tun_ready=info.get('tun') == 'succ', hostname=(info.get('host') or {}).get('hostname'))
        try:
            signal = request('/glp/sipstate', transport=True)
            result['connected'] = signal.get('result') == 0 and signal.get('state') == 1
            peers = request('/glp/peerlist', transport=True)
            active = set(peers) if isinstance(peers, list) else set()
        except NodeBabyError as error:
            active = set()
            result['transport_error'] = str(error)
        routes = request('/tun/routers')
        if not isinstance(routes, dict) or routes.get('code') != 0 or not isinstance(routes.get('states'), list):
            raise NodeBabyError('节点小宝映射列表格式不兼容，请在原生客户端核对')
        for route in routes['states']:
            try:
                address = ipaddress.IPv4Address(route['map'])
                prefix = int(route['prefix'])
                target = ipaddress.IPv4Address(route['ipv4'])
                network = ipaddress.IPv4Network(f'{address}/{prefix}', strict=False)
            except (ValueError, KeyError, TypeError):
                continue
            own = route.get('pid') == info.get('peerid')
            result['mappings'].append(dict(
                id=f'{address}/{prefix}', address=str(address), prefix=prefix, target=str(target),
                name=route.get('domain') or str(target), self=own,
                link_active=not own and route.get('pid') in active,
                group=str(ipaddress.IPv4Network(f'{address}/24', strict=False)) if prefix == 32 else str(network)))
            if own:
                result['addresses'].append(str(address))
        result['mappings'].sort(key=lambda item: int(ipaddress.IPv4Address(item['address'])))
    except NodeBabyError as error:
        result['error'] = str(error)
    return result


def open_client():
    if sys.platform != 'darwin' or not APP.exists():
        raise NodeBabyError('当前主机未发现可打开的节点小宝 macOS 客户端')
    try:
        subprocess.run(['/usr/bin/open', '-a', str(APP)], check=True, timeout=8,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        raise NodeBabyError('无法打开节点小宝客户端，请检查本机安装状态') from None


def probe(identifier, port):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('请输入 1–65535 的服务端口')
    item = next((item for item in status()['mappings'] if item['id'] == identifier), None)
    if not item or item['prefix'] != 32:
        raise ValueError('请选择当前映射列表中的单个设备地址')
    started = time.monotonic()
    try:
        with socket.create_connection((item['address'], port), timeout=3):
            return dict(address=item['address'], port=port, reachable=True,
                        latency_ms=round((time.monotonic() - started) * 1000, 1))
    except ConnectionRefusedError:
        message = '连接被拒绝，请检查目标服务是否已启动并监听此端口'
    except TimeoutError:
        message = '连接超时，请检查目标设备、服务端口和组网连接'
    except OSError:
        message = '连接失败，请检查组网路由与目标服务'
    return dict(address=item['address'], port=port, reachable=False, message=message)
