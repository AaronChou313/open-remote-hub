"""Local IPv4 network inventory and bounded, user-requested discovery."""
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import socket
import threading
import time

import psutil
from app import platforms, workspace_store as store

lock = threading.RLock()
scan_lock = threading.Lock()
last_counters = {}
checks = {}


def interfaces():
    stats = psutil.net_if_stats()
    counters = psutil.net_io_counters(pernic=True)
    now = time.monotonic()
    rows = []
    for name, addresses in psutil.net_if_addrs().items():
        if name.startswith(('lo', 'utun', 'tun', 'tap', 'tailscale', 'docker', 'veth', 'vmenet', 'bridge', 'vmnet', 'br-')):
            continue
        stat = stats.get(name)
        if not stat or not stat.isup:
            continue
        mac = next((item.address.lower() for item in addresses if item.family == psutil.AF_LINK), '')
        for item in addresses:
            if item.family != socket.AF_INET or not item.netmask:
                continue
            network = ipaddress.IPv4Network(f'{item.address}/{item.netmask}', strict=False)
            if not ipaddress.ip_address(item.address).is_private or network.prefixlen >= 31:
                continue
            rate = counters.get(name)
            with lock:
                previous = last_counters.get(name)
                last_counters[name] = (now, rate)
            elapsed = now - previous[0] if previous else 0
            upload = max(0, (rate.bytes_sent - previous[1].bytes_sent) / elapsed) if rate and previous and previous[1] and elapsed else None
            download = max(0, (rate.bytes_recv - previous[1].bytes_recv) / elapsed) if rate and previous and previous[1] and elapsed else None
            rows.append(dict(name=name, ip=item.address, netmask=item.netmask, network=str(network), mac=mac,
                             speed_mbps=stat.speed, upload=upload, download=download))
    return rows


def status():
    links = interfaces()
    warnings = []
    try:
        details = platforms.lan_details()
    except (RuntimeError, OSError, ValueError):
        details = dict(gateways=[], dns=[])
        warnings.append('网关或 DNS 信息暂不可用')
    try:
        neighbors = platforms.lan_neighbors()
    except (RuntimeError, ValueError):
        neighbors = []
        warnings.append('邻居列表暂不可用')
    saved = {row['id']:row for row in store.rows('lan-device')}
    notes = {row['id']:row for row in store.rows('lan-note')}
    own = {row['ip']:row for row in links}
    devices = {}
    link_names = {link['name'] for link in links}
    for row in [*saved.values(), *neighbors, *[dict(ip=row['ip'], mac=row['mac'], interface=row['name']) for row in links]]:
        if row.get('interface') not in link_names:
            continue
        try:
            address = ipaddress.IPv4Address(row['ip'])
        except ValueError:
            continue
        if not any(address in ipaddress.IPv4Network(link['network']) for link in links) or address.is_multicast or row.get('mac') == 'ff:ff:ff:ff:ff:ff':
            continue
        if any(str(address) in (str(ipaddress.IPv4Network(link['network']).broadcast_address), str(ipaddress.IPv4Network(link['network']).network_address)) for link in links):
            continue
        key = 'local-host' if row['ip'] in own else row.get('mac') or row['ip']
        device = devices.setdefault(key, dict(id=key, mac=row.get('mac', ''), macs=[], addresses=[], interfaces=[], state='known', checked_at=None, last_seen=saved.get(key, {}).get('last_seen')))
        if row.get('mac') and row['mac'] not in device['macs']:
            device['macs'].append(row['mac'])
        if row['ip'] not in device['addresses']:
            device['addresses'].append(row['ip'])
        if row.get('interface') and row['interface'] not in device['interfaces']:
            device['interfaces'].append(row['interface'])
        with lock:
            result = checks.get(row['ip'])
        if row['ip'] in own:
            device.update(state='self', name=socket.gethostname())
        elif device['state'] != 'self' and result and time.time() - result['checked_at'] < 90:
            if result['online'] or device['state'] != 'online':
                device.update(state='online' if result['online'] else 'unresponsive', checked_at=result['checked_at'])
        device['note'] = notes.get(key, {}).get('note', '')
        device['gateway'] = any(entry['address'] in device['addresses'] for entry in details['gateways'])
    return dict(interfaces=links, devices=sorted(devices.values(), key=lambda row: int(ipaddress.IPv4Address(row['addresses'][0]))),
                warnings=warnings, **details)


def scan():
    if not scan_lock.acquire(blocking=False):
        raise ValueError('设备发现正在进行，请稍后刷新')
    try:
        current = status()
        targets = {address for row in current['devices'] for address in row['addresses']}
        targets.update(row['address'] for row in current['gateways'] if any(ipaddress.ip_address(row['address']) in ipaddress.ip_network(link['network']) for link in current['interfaces']))
        partial = False
        for network in {row['network'] for row in current['interfaces']}:
            network = ipaddress.ip_network(network)
            if network.num_addresses <= 256:
                targets.update(str(address) for address in network.hosts())
            else:
                partial = True
        def check(address):
            online = platforms.lan_ping(address)
            with lock:
                checks[address] = dict(online=online, checked_at=time.time())
        with ThreadPoolExecutor(max_workers=32) as pool:
            list(pool.map(check, sorted(targets)))
        result = status()
        saved = {item['id']:item for item in store.rows('lan-device')}
        for row in result['devices']:
            if row['state'] in ('self','online'):
                previous = saved.get(row['id'])
                store.save('lan-device', dict(ip=row['addresses'][0], mac=row['mac'], interface=row['interfaces'][0] if row['interfaces'] else '', last_seen=time.time()), row['id'], previous['revision'] if previous else None)
        if partial:
            result['warnings'].append('较大的网段本次仅检测已发现设备与网关')
        return result
    finally:
        scan_lock.release()


def save_note(identifier, note):
    if not isinstance(identifier, str) or not isinstance(note, str) or len(note) > 120:
        raise ValueError('备注最多 120 个字符')
    if identifier not in {row['id'] for row in status()['devices']}:
        raise ValueError('设备已不在当前局域网列表中')
    previous = next((row for row in store.rows('lan-note') if row['id'] == identifier), None)
    store.save('lan-note', dict(note=note.strip()), identifier, previous['revision'] if previous else None)
    return dict(ok=True)
