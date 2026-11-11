"""Cancelable, bounded diagnostic jobs using actual system OpenSSH."""
from concurrent.futures import ThreadPoolExecutor
import re
import secrets
import socket
import threading
import time

from fastapi import HTTPException
from app.ssh import configuration as config, hosts, storage as store
from app.ssh.process import run, CommandFailure
from app.ssh.terminals import argv, connection

pool = None
lock = threading.RLock()
active = {}


def classification(text):
    lower = text.lower()
    if 'remote host identification has changed' in lower or 'host key verification failed' in lower:
        return 'host_key_error', '主机指纹未知或已变化，请先核验主机指纹'
    if 'connection refused' in lower:
        return 'connection_refused', '目标拒绝连接，请检查 SSH 服务和端口'
    if any(s in lower for s in ('no route to host', 'network is unreachable', 'could not resolve hostname', 'operation timed out', 'connection timed out')):
        return 'network_unreachable', '网络、DNS 或目标端口不可达'
    if 'permission denied' in lower:
        if 'password' in lower or 'keyboard-interactive' in lower or 'encrypted' in lower:
            return 'interactive_required', '需要密码、密钥口令或交互式认证，请进入终端'
        return 'authentication_failed', '公钥认证失败，请检查用户名、密钥和远端授权'
    if 'no matching' in lower or 'kex_exchange_identification' in lower:
        return 'handshake_failed', 'SSH 握手失败，请检查服务端算法和访问策略'
    return 'ssh_failed', 'SSH 未完成，请进入原生终端查看交互提示'


def start(host, kind='diagnose'):
    global pool
    if kind not in ('diagnose', 'scan'):
        raise HTTPException(400, '未知诊断类型')
    config.alias(host)
    inventory = config.inventory()
    found = next((row for row in inventory['connections'] if row['alias'].lower() == host.lower()), None)
    if not found:
        raise HTTPException(404, 'SSH 连接不存在')
    if found['managed'] and not inventory['linked']:
        raise HTTPException(409, '请先在 SSH 配置中接入原生 Config')
    config.assert_trusted()
    with lock:
        if len(active) >= 4:
            raise HTTPException(429, '已有四个 SSH 检查正在运行，请等待或取消')
        if pool is None:
            pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='ssh-diagnostic')
        token = secrets.token_hex(16)
        event = threading.Event()
        active[token] = event
        store.put('job', token, dict(host=host, kind=kind, state='queued', stage='等待执行', created=time.time()))
        pool.submit(worker, token, event)
    return dict(id=token)


def worker(token, cancel):
    row = store.get('job', token)
    try:
        row.update(state='running', stage='读取生效配置')
        store.put('job', token, row)
        if row['kind'] == 'scan':
            row.update(stage='扫描未经信任的主机公钥')
            store.put('job', token, row)
            row['result'] = hosts.scan(row['host'], cancel)
        else:
            hostname, port, _, values = hosts.address(row['host'], cancel)
            row.update(stage='检查 TCP 端口', checks=[])
            store.put('job', token, row)
            if values.get('proxyjump', 'none') == 'none':
                # DNS is bounded by the overall SSH subprocess below. A resolver can
                # block independently, so the direct TCP probe uses an IP when known.
                try:
                    import ipaddress
                    ipaddress.ip_address(hostname)
                    with socket.create_connection((hostname, int(port)), timeout=3):
                        row['checks'].append(dict(kind='tcp', status='reachable'))
                except ValueError:
                    row['checks'].append(dict(kind='tcp', status='checked_by_ssh'))
                except OSError as error:
                    status = 'connection_refused' if getattr(error, 'errno', None) in (61, 111) else 'network_unreachable'
                    row['checks'].append(dict(kind='tcp', status=status))
            else:
                row['checks'].append(dict(kind='tcp', status='via_proxyjump'))
            row.update(stage='检查 SSH 握手、指纹与公钥认证')
            store.put('job', token, row)
            command = argv(row['host'], interactive=False)
            command.insert(1, '-v')
            try:
                run(command + ['true'], timeout=18, cancel=cancel)
                row['result'] = dict(status='authenticated', message='SSH 握手、主机指纹及公钥认证成功')
            except CommandFailure as error:
                status, message = classification(error.output)
                row['result'] = dict(status=status, message=message)
        row.update(state='completed', stage='检查完成')
    except HTTPException as error:
        row.update(state='cancelled' if cancel.is_set() else 'failed', stage=error.detail,
                   result=dict(status='timeout' if error.status_code == 504 else 'failed', message=error.detail))
    except Exception:
        row.update(state='failed', stage='SSH 检查失败，请核验配置后重试')
    finally:
        row['ended'] = time.time()
        store.put('job', token, row)
        with lock:
            active.pop(token, None)


def get(token):
    row = store.get('job', token)
    if not row:
        raise HTTPException(404, '诊断任务不存在')
    if row['state'] in ('queued', 'running') and token not in active:
        row.update(state='interrupted', stage='服务重启已中断检查，请重新测试')
    return row


def stop(token):
    row = get(token)
    with lock:
        event = active.get(token)
        if event:
            event.set()
    return dict(row, cancellation_requested=bool(event))


def shutdown():
    global pool
    with lock:
        previous = pool
        pool = None
        for event in active.values():
            event.set()
    if previous:
        previous.shutdown(wait=True)
