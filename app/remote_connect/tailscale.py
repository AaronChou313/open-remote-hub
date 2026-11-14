"""ORN LocalAPI consumer, preserving the console network response contract."""
import ipaddress
import json
import os
from pathlib import Path
import sys
import httpx
import threading
import time
from urllib.parse import urlsplit

lock = threading.RLock()
operation = None
PREFERENCES = ('accept-dns', 'accept-routes', 'shields-up', 'exit-node', 'exit-node-allow-lan-access')


class TailscaleError(RuntimeError):
    pass


def token_file():
    default = (Path.home()/'Library/Application Support/orn-agent/api.token' if sys.platform=='darwin'
               else Path(os.environ.get('APPDATA') or os.environ.get('XDG_CONFIG_HOME') or str(Path.home()/'.config'))/'orn-agent/api.token')
    return Path(os.environ.get('ORH_ORN_API_TOKEN_FILE',str(default))).expanduser()


def binary():
    return str(token_file()) if token_file().is_file() else None


def request(path, body=None, timeout=10):
    base = os.environ.get('ORH_ORN_API_URL','http://127.0.0.1:4789').rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost','::1') or parsed.username or parsed.path:
        raise TailscaleError('ORN LocalAPI 地址必须是 loopback HTTP 入口')
    try:
        token=token_file().read_text().strip()
        with httpx.Client(timeout=timeout,trust_env=False) as client:
            response=client.request('GET' if body is None else 'POST',base+'/api/v1'+path,
                                    json=body,headers={'Authorization':'Bearer '+token})
    except FileNotFoundError:
        raise TailscaleError('请先安装并启动 ORN Agent') from None
    except httpx.TimeoutException:
        raise TailscaleError('ORN 请求超时，请刷新状态核对') from None
    except (httpx.HTTPError,OSError):
        raise TailscaleError('ORN 本地服务不可用，请检查 Agent 状态') from None
    if response.status_code>=400:
        raise TailscaleError(response.json().get('detail','ORN 操作未完成'))
    return response.json()


def native_peer(value):
    return dict(ID=value.get('id'),HostName=value.get('hostname'),DNSName=value.get('dns_name'),
                TailscaleIPs=value.get('ips',[]),Online=value.get('online',False),
                Active=value.get('path') in ('direct','relay'),CurAddr=value.get('direct_addr',''),
                Relay=value.get('relay',''),RxBytes=value.get('rx',0),TxBytes=value.get('tx',0))


def command(arguments, timeout=10):
    if arguments==['status','--json']:
        value=request('/status',timeout=timeout)
        peers=request('/peers',timeout=timeout)
        raw=dict(Version=value.get('version'),BackendState=value.get('backend_state'),
                 Self=native_peer(value.get('device',{})),Peer={peer['id']:native_peer(peer) for peer in peers},
                 Health=value.get('health',[]),AuthURL='',
                 CurrentTailnet={'Name':'ORN','MagicDNSSuffix':value.get('network',''),'MagicDNSEnabled':value.get('magic_dns',False)})
        return json.dumps(raw)
    if arguments==['get','--json']:
        return '{}'
    if arguments==['netcheck']:
        return json.dumps(request('/netcheck',{},timeout=timeout),ensure_ascii=False,indent=2)
    if arguments and arguments[0]=='ping':
        value=request('/ping',{'peer_ip':arguments[-1]},timeout=timeout)
        if value.get('Err'):raise TailscaleError(value['Err'])
        route=value.get('Endpoint') or 'DERP '+str(value.get('DERPRegionCode') or value.get('DERPRegionID'))
        return f"{value.get('IP')} · {value.get('LatencySeconds',0)*1000:.1f} ms · {route}"
    if arguments and arguments[0] in ('up','down'):
        return json.dumps(request('/control',{'action':'connect' if arguments[0]=='up' else 'disconnect'},timeout=timeout))
    raise TailscaleError('此设置请在 ORN 本地入口管理')


def json_command(arguments):
    try:
        return json.loads(command(arguments))
    except ValueError:
        raise TailscaleError('ORN 返回了无法解析的状态') from None


def preferences():
    values = json_command(['get', '--json'])
    return {name: values.get(name) for name in PREFERENCES} if values else None


def peer(value):
    addresses = value.get('TailscaleIPs') or []
    return dict(id=value.get('ID'), hostname=value.get('HostName') or '', dns=(value.get('DNSName') or '').rstrip('.'),
                addresses=addresses, os=value.get('OS') or '', online=bool(value.get('Online')),
                active=bool(value.get('Active')), direct_address=value.get('CurAddr') or '',
                relay=value.get('Relay') or '', route='direct' if value.get('CurAddr') else 'relay' if value.get('Active') and value.get('Relay') else 'idle',
                rx=value.get('RxBytes') or 0, tx=value.get('TxBytes') or 0,
                exit_node=bool(value.get('ExitNode')), exit_node_available=bool(value.get('ExitNodeOption')),
                last_seen=value.get('LastSeen'), key_expiry=value.get('KeyExpiry'))


def safe_url(value):
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in ('http', 'https') and parsed.hostname else None
    except ValueError:
        return None


def status():
    with lock:
        last_operation = dict(operation) if operation else None
    if not binary():
        return dict(available=False, error='未发现 ORN Agent', peers=[], last_operation=last_operation)
    try:
        value = json_command(['status', '--json'])
    except TailscaleError as error:
        return dict(available=True, reachable=False, error=str(error), peers=[], last_operation=last_operation)
    network = value.get('CurrentTailnet') or {}
    result = dict(backend='orn', available=True, reachable=True, state=value.get('BackendState'), version=value.get('Version'),
                  device=peer(value.get('Self') or {}), network=network.get('MagicDNSSuffix') or network.get('Name'),
                  magic_dns=bool(network.get('MagicDNSEnabled')), health=value.get('Health') or [],
                  auth_url=safe_url(value.get('AuthURL') or ''),
                  peers=sorted((peer(item) for item in (value.get('Peer') or {}).values()), key=lambda item:(not item['online'], item['hostname'].casefold())),
                  last_operation=last_operation)
    try:
        result['preferences'] = preferences()
    except TailscaleError as error:
        result.update(preferences=None, preference_error=str(error))
    return result


def save_preferences(changes, before, confirm=False):
    if not isinstance(changes, dict) or not isinstance(before, dict):
        raise ValueError('请选择要修改的组网设置')
    for name, value in changes.items():
        if name not in PREFERENCES:
            raise ValueError('不支持的组网设置')
        if name == 'exit-node':
            nodes = status()
            candidates = {ip for node in nodes['peers'] if node['exit_node_available'] for ip in node['addresses']}
            candidates.add('')
            if value not in candidates:
                raise ValueError('请选择组网中可用的出口节点')
        elif type(value) is not bool:
            raise ValueError('组网开关值无效')
    with lock:
        current = preferences()
        if current is None:
            raise ValueError('此设置请在 ORN 本地入口管理')
        if any(name not in before or current[name] != before[name] for name in changes):
            raise ValueError('组网设置已在其他窗口更改，请刷新后重试')
        actual = {name:value for name,value in changes.items() if current[name] != value}
        disruptive = actual.get('shields-up') is True or 'exit-node' in actual or 'exit-node-allow-lan-access' in actual
        if disruptive and not confirm:
            raise ValueError('请确认更改入站连接或出口路由，当前远程访问可能中断')
        if actual:
            flags = [f'--{name}={str(value).lower() if type(value) is bool else value}' for name,value in actual.items()]
            command(['set', *flags])
        return preferences()


def run_operation(action):
    global operation
    try:
        if action in ('disconnect', 'reconnect'):
            command(['down', '--accept-risk=lose-ssh'])
        if action in ('connect', 'reconnect'):
            command(['up'], timeout=12)
        with lock:
            operation = dict(action=action, state='done', time=time.time())
    except TailscaleError as error:
        with lock:
            operation = dict(action=action, state='error', message=str(error), time=time.time())


def control(action, confirm=False):
    global operation
    if action not in ('connect', 'disconnect', 'reconnect'):
        raise ValueError('不支持的组网操作')
    if action != 'connect' and not confirm:
        raise ValueError('请确认断开或重连 ORN，当前组网访问会中断')
    with lock:
        if operation and operation['state'] == 'pending':
            raise ValueError('已有组网操作正在执行')
        operation = dict(action=action, state='pending', time=time.time())
        return dict(operation)


def ping(identifier):
    nodes = status()
    target = next((node for node in nodes['peers'] if node['id'] == identifier), None)
    if not target or not target['addresses']:
        raise ValueError('此组网设备已不存在，请刷新列表')
    address = next((address for address in target['addresses'] if ':' not in address), target['addresses'][0])
    output = command(['ping', '--c=3', '--timeout=3s', '--until-direct=true', address], timeout=12)
    return dict(target=address, output=output)


def netcheck():
    return dict(output=command(['netcheck'], timeout=15))


def access_urls():
    from app.main import NETWORK, PORT
    scheme = 'https' if os.environ.get('ORH_TLS_CERT_FILE') else 'http'
    urls = []
    for host in sorted(NETWORK.hosts):
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            continue
        if address.version == 4 and (address.is_private or address in ipaddress.ip_network('100.64.0.0/10')) and not address.is_loopback:
            urls.append(f'{scheme}://{host}:{PORT}/')
    return urls
