"""Local NodeBabyLink 4.5.3 status adapter. Native settings stay with its client."""
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode
from urllib.error import URLError
from urllib.request import build_opener, ProxyHandler

APP = Path('/Applications/节点小宝.app')
http = build_opener(ProxyHandler({}))
checks = {}
check_lock = threading.Lock()


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


def snapshot():
    info = request('/detect/version')
    if not isinstance(info, dict) or info.get('name') != 'NodeBabyLinkService':
        raise NodeBabyError('本地端口返回了其他服务，请核对节点小宝 API 端口')
    routes = request('/tun/routers')
    if not isinstance(routes, dict) or routes.get('code') != 0 or not isinstance(routes.get('states'), list):
        raise NodeBabyError('节点小宝映射列表格式不兼容，请在原生客户端核对')
    return info, routes['states']


def connection(peer_id):
    value = request('/glp/peerinfo?' + urlencode({'remote_peerid': peer_id}), transport=True)
    if value.get('result') != 0 or value.get('errcode', 0) != 0:
        return None
    families = (('lan', '局域网直连', ('lan', 'lanu')), ('p2p', 'P2P 直连', ('nptt', 'nptu', 'npu')),
                ('relay', '中继', ('relay', 'relayu')))
    for _, label, flags in families:
        if any(value.get(flag) for flag in flags):
            delays = [value.get(flag + '_latency') for flag in flags]
            delays = [delay for delay in delays if type(delay) in (int, float) and delay >= 0]
            return dict(state='online', route=label, latency_ms=min(delays) if delays else None)
    return None


def status():
    result = dict(available=APP.exists() or Path('/usr/local/nblink/NodeBabyLinkService').exists(),
                  ready=False, connected=False, tun_ready=False, mappings=[], addresses=[],
                  can_open=sys.platform == 'darwin' and APP.exists())
    try:
        info, routes = snapshot()
        result.update(available=True, ready=True, version=info.get('version'), pid=info.get('pid'),
                      tun_ready=info.get('tun') == 'succ', hostname=(info.get('host') or {}).get('hostname'))
        try:
            signal = request('/glp/sipstate', transport=True)
            result['connected'] = signal.get('result') == 0 and signal.get('state') == 1
            transport_ready = True
        except NodeBabyError as error:
            transport_ready = False
            result['transport_error'] = str(error)
        connections = {}
        for route in routes:
            try:
                address = ipaddress.IPv4Address(route['map'])
                prefix = int(route['prefix'])
                target = ipaddress.IPv4Address(route['ipv4'])
                network = ipaddress.IPv4Network(f'{address}/{prefix}', strict=False)
            except (ValueError, KeyError, TypeError):
                continue
            own = route.get('pid') == info.get('peerid')
            peer_id = route.get('pid')
            if peer_id not in connections:
                try:
                    connections[peer_id] = connection(peer_id) if transport_ready and not own else None
                except NodeBabyError:
                    connections[peer_id] = None
            with check_lock:
                checked = dict(checks.get(peer_id, {}))
            if time.time() - checked.get('checked_at', 0) > 30:
                checked = {}
            live = dict(state='self', route='本机', latency_ms=None) if own else connections[peer_id]
            if live and checked.get('checked_at'):
                live['checked_at'] = checked['checked_at']
            cached_failure = checked if checked.get('state') in ('unreachable', 'unknown') else {}
            live = live or cached_failure or dict(state='unknown', route='等待检测', latency_ms=None)
            result['mappings'].append(dict(
                id=f'{address}/{prefix}', address=str(address), prefix=prefix, target=str(target),
                name=route.get('domain') or str(target), self=own,
                link_active=live['state'] == 'online', connection=live,
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


def check_connections(identifiers):
    if not isinstance(identifiers, list) or len(identifiers) > 64 or any(not isinstance(value, str) for value in identifiers):
        raise ValueError('请选择需要检测的设备，单次最多 64 个映射')
    info, routes = snapshot()
    selected = {}
    for identifier in identifiers:
        route = next((item for item in routes if f"{item['map']}/{item['prefix']}" == identifier), None)
        if not route or route['prefix'] != 32:
            raise ValueError('请选择当前映射列表中的单个设备地址')
        selected[route['pid']] = route
    def check(route):
        peer_id = route['pid']
        result = dict(state='unreachable', route='未连通', latency_ms=None)
        try:
            if peer_id == info.get('peerid'):
                result.update(state='self', route='本机')
            else:
                # A TUN SYN/ACK only means the local proxy accepted the socket.
                # Trigger native peer discovery, then verify its real transport.
                try:
                    with socket.create_connection((str(ipaddress.IPv4Address(route['map'])), 8765), timeout=1):
                        pass
                except OSError:
                    pass
                deadline = time.monotonic() + 3
                while True:
                    live = connection(peer_id)
                    if live:
                        result = live
                        break
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(.25)
        except NodeBabyError:
            result.update(state='unknown', route='本地接口不可用')
        result['checked_at'] = time.time()
        with check_lock:
            checks[peer_id] = result
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(check, selected.values()))
    return status()
