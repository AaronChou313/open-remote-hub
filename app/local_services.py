"""Host service inventory from service managers, TCP listeners and Docker ports."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import ipaddress
import shutil
import threading
import time

import httpx
import psutil
from fastapi import APIRouter, HTTPException
from app import platforms

router = APIRouter(prefix='/api/local-services', tags=['local-services'])
probe_lock = threading.RLock()
probe_cache = {}


def process(pid):
    if not pid:
        return None
    try:
        data = psutil.Process(pid).as_dict(attrs=['pid','ppid','name','cmdline','create_time','username','cwd','exe'], ad_value=None)
        data['command'] = data.pop('cmdline') or []
        data['created'] = data.pop('create_time')
        return data
    except psutil.Error:
        return None


def loopback(address):
    try:
        return ipaddress.ip_address(address.split('%')[0]).is_loopback
    except ValueError:
        return False


def endpoint(value):
    address = value['address']
    return dict(value, binding='loopback' if loopback(address) else 'all' if address in ('*','0.0.0.0','::') else 'interface', protocol='tcp')


def identify_web(value):
    address = value['address']
    if address in ('*', '0.0.0.0'):
        address = '127.0.0.1'
    elif address == '::':
        address = '::1'
    host = '[' + address + ']' if ':' in address else address
    # Only local OS listeners / Docker bindings reach this function. Never use a
    # browser-supplied destination, credentials, proxies, or redirect target.
    for scheme in (('https','http') if value['port'] in (443,8443,9443) else ('http','https')):
        try:
            with httpx.Client(timeout=.65, verify=False, trust_env=False, follow_redirects=False) as client:
                response = client.head(f'{scheme}://{host}:{value["port"]}/')
            return dict(protocol=scheme, http_status=response.status_code, server=response.headers.get('server','')[:120])
        except (httpx.HTTPError, httpx.InvalidURL):
            continue
    return dict(protocol='tcp')


def docker_services():
    if not shutil.which('docker'):
        return []
    from app.main import cli, jsonlines
    identifiers = cli(['docker','ps','-q'], 3).split()
    if not identifiers:
        return []
    template = '{"id":{{json .Id}},"name":{{json .Name}},"ports":{{json .NetworkSettings.Ports}},"started":{{json .State.StartedAt}}}'
    result = []
    for container in jsonlines(cli(['docker','inspect','--format',template,*identifiers], 4)):
        ports = []
        for target, bindings in (container['ports'] or {}).items():
            if not target.endswith('/tcp'):
                continue
            for binding in bindings or []:
                ports.append(endpoint(dict(address=binding.get('HostIp') or '0.0.0.0', port=int(binding['HostPort']), target=target)))
        result.append(dict(id='docker-' + container['id'], container=container['id'], name=container['name'].lstrip('/'),
                           source='Docker', scope='container', running=True, status='running', pid=None,
                           process=None, created=datetime.fromisoformat(container['started'].replace('Z','+00:00')).timestamp(),
                           endpoints=ports))
    return result


def key(row):
    return hashlib.sha256((row['source'] + ':' + row.get('scope','') + ':' + row['name']).encode()).hexdigest()[:20]


def binding_key(item):
    return ('*' if item['address'] in ('*','0.0.0.0','::') else item['address'], item['port'])


@router.get('')
def inventory(probe: bool = True, force: bool = False):
    warnings = []
    rows = []
    by_pid = {}
    for scope in ('user','system'):
        try:
            units = platforms.host.services(scope)
        except (RuntimeError, OSError, ValueError) as error:
            warnings.append(('用户' if scope=='user' else '系统') + '服务列表暂不可读 · ' + str(error)[:180])
            continue
        for unit in units:
            row = dict(unit, id=key(unit), running=bool(unit.get('pid')) or unit.get('status') in ('active','running'),
                       process=None, created=None, endpoints=[])
            rows.append(row)
            if row.get('pid'):
                by_pid.setdefault(row['pid'], row)
    try:
        listeners = platforms.host.listeners()
    except (psutil.Error, RuntimeError, OSError) as error:
        listeners = []
        warnings.append('监听端口暂不可读 · ' + str(error)[:180])
    try:
        containers = docker_services()
    except (HTTPException, RuntimeError, OSError, ValueError) as error:
        containers = []
        warnings.append('Docker 服务暂不可读 · ' + (str(error.detail) if isinstance(error,HTTPException) else str(error))[:180])
    from app.main import tasks_list
    for task in tasks_list():
        pid = task.get('pid') if task['running'] else None
        if pid in by_pid:
            by_pid[pid]['task'] = task['id']
            continue
        row = dict(id='task-' + task['id'], task=task['id'], name=task['name'], source='项目进程', scope='user',
                   running=task['running'], status='running' if task['running'] else 'inactive', pid=pid,
                   process=None, created=task.get('created'), endpoints=[])
        rows.append(row)
        if pid:
            by_pid[pid] = row
    published = {binding_key(item):row for row in containers for item in row['endpoints']}
    seen = set()
    for listener in listeners:
        identity = (listener.get('pid'),listener['address'],listener['port'])
        if identity in seen:
            continue
        seen.add(identity)
        item = endpoint(listener)
        container = published.get(binding_key(item))
        if container:
            for binding in container['endpoints']:
                if binding_key(binding) == binding_key(item):
                    binding['pid'] = listener.get('pid')
            continue
        pid = listener.get('pid')
        row = by_pid.get(pid) if pid else None
        if not row:
            info = process(pid)
            created = info.get('created') if info else None
            identity = f'{pid}-{created}' if pid else hashlib.sha256(f'{listener["address"]}:{listener["port"]}'.encode()).hexdigest()[:20]
            row = dict(id=f'process-{identity}',
                       name=(info or {}).get('name') or listener.get('name') or '未关联进程', pid=pid,
                       source='进程', scope='host', running=True, status='running', process=info,
                       created=created, endpoints=[])
            rows.append(row)
            if pid:
                by_pid[pid] = row
        row['endpoints'].append(item)
    rows += containers
    for row in rows:
        if row.get('pid') and not row['process']:
            row['process'] = process(row['pid'])
        if row['process']:
            row['created'] = row['process']['created']
        row['apple'] = row['name'].startswith(('com.apple.', 'application.com.apple.'))
    if probe:
        now = time.monotonic()
        requests = {}
        for row in rows:
            for item in row['endpoints']:
                identity = (row['id'], row.get('created'), item['address'], item['port'])
                requests.setdefault(identity, item)
        with probe_lock:
            stale = {identity:item for identity,item in requests.items() if force or identity not in probe_cache or now-probe_cache[identity][0]>90}
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(identify_web, stale.values()))
        with probe_lock:
            for identity,result in zip(stale,results):
                probe_cache[identity] = (time.monotonic(),result)
            for identity in list(probe_cache):
                if now-probe_cache[identity][0]>180:
                    del probe_cache[identity]
    with probe_lock:
        for row in rows:
            for item in row['endpoints']:
                identity = (row['id'],row.get('created'),item['address'],item['port'])
                if identity in probe_cache:
                    item.update(probe_cache[identity][1])
    rows.sort(key=lambda row:(not any(item['protocol'] in ('http','https') for item in row['endpoints']), not bool(row['endpoints']), not row['running'], row['name'].casefold()))
    return dict(services=rows, warnings=warnings, time=time.time())


@router.get('/{identifier}')
def detail(identifier: str):
    row = next((row for row in inventory(probe=False)['services'] if row['id']==identifier),None)
    if not row:
        raise HTTPException(404, '此服务已退出或发生变化，请刷新列表')
    if row['source'] in ('launchd','systemd'):
        try:
            row['details'] = platforms.service_detail(row['name'],row['scope'])
        except RuntimeError as error:
            row['details'] = dict(note=str(error))
    elif row['source']=='Docker':
        from app.main import logs
        row['details'] = dict(logs=logs(row['container'],None,False))
    elif row.get('task'):
        from app.main import task_logs
        row['details'] = dict(logs={'运行输出':task_logs(row['task'])['output']})
    else:
        row['details'] = dict(note='独立进程没有登记文件日志，启动命令和工作目录见进程信息。')
    return row
