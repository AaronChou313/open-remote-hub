"""Embedded ORN data plane: one ORH install, one user service.

The Go networking agent stays a separate process for crash isolation, but ORH
owns its lifecycle. Ownership survives an ORH restart through a pidfile, so a
hard-killed console never leaves an unmanaged mesh process behind. The standard
ORN config path is reused, keeping the existing enrollment, device UUID and API
token. When a standalone ORN service is running, ORH observes it instead of
starting a duplicate until an explicit takeover.
"""
import ipaddress
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import psutil

ROOT = Path(__file__).resolve().parent.parent
LOCK = threading.RLock()
RESTARTS = 0
ERROR = ''
NOTE = ''
STOP = threading.Event()
THREAD = None
TAKEOVER = False
SPAWN = threading.Lock()
SERVICE_CACHE = (0.0, None)


def target():
    system = 'windows' if sys.platform == 'win32' else 'darwin' if sys.platform == 'darwin' else 'linux'
    machine = platform.machine().lower()
    architecture = 'arm64' if machine in ('arm64', 'aarch64') else 'amd64'
    return system, architecture


def binary():
    name = 'orn-agent.exe' if sys.platform == 'win32' else 'orn-agent'
    candidates = [os.environ.get('ORH_ORN_BIN'), str(ROOT / 'bin' / name),
                  str(ROOT.parent / 'open-remote-net' / 'dist' / f'orn-agent-{target()[0]}-{target()[1]}'),
                  shutil.which('orn-agent')]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def default_config():
    if sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    elif sys.platform == 'win32':
        base = Path(os.environ.get('APPDATA') or Path.home() / 'AppData' / 'Roaming')
    else:
        base = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    return base / 'orn-agent' / 'config.json'


def config_path():
    return Path(os.environ.get('ORH_ORN_CONFIG', str(default_config()))).expanduser()


def token_path():
    return config_path().parent / 'api.token'


def log_path():
    from app.main import DATA
    return DATA / 'orn.log'


def pid_path():
    return log_path().parent / 'orn.pid'


def enabled():
    value = os.environ.get('ORH_ORN_ENABLED', 'auto').strip().lower()
    if value in ('0', 'false', 'off', 'no'):
        return False
    return binary() is not None


def token():
    try:
        return token_path().read_text().strip()
    except OSError:
        return ''


def api_base():
    """The loopback base this config actually listens on."""
    address = '127.0.0.1:4789'
    try:
        value = json.loads(config_path().read_text())
        address = value.get('api_addr') or address
    except (OSError, ValueError):
        pass
    return 'http://' + address


def probe(timeout=2):
    """True when an ORN process for this config answers its loopback API."""
    from app.remote_connect import tailscale
    if not token():
        return False
    try:
        tailscale.request('/health', timeout=timeout, base=api_base(), token=token())
        return True
    except Exception:
        return False


def published():
    """Ports this ORH exposes through the mesh: console, gateway and RustDesk."""
    from app.main import PORT
    gateway = int(os.environ.get('ORH_DSH_GATEWAY_PORT', '8767'))
    return {'21118': '127.0.0.1:21118', str(PORT): f'127.0.0.1:{PORT}', str(gateway): f'127.0.0.1:{gateway}'}


def ensure_config():
    path = config_path()
    if path.exists():
        return False
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    value = dict(control_url=os.environ.get('ORH_ORN_CONTROL_URL', 'https://hs.openremotehub.top'),
                 hostname=(platform.node() or 'openremotehub') + '-orn',
                 state_dir=str(path.parent / 'state'),
                 api_addr=os.environ.get('ORH_ORN_API_ADDR', '127.0.0.1:4789'),
                 cloud=dict(base_url=os.environ.get('ORH_ORN_CLOUD_URL', 'https://cloud.openremotehub.top')),
                 publish=published())
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
    temporary.replace(path)
    return True


def owner():
    """The ORN process this install started, validated by pid, start time and argv."""
    try:
        value = json.loads(pid_path().read_text())
        process = psutil.Process(value['pid'])
        if abs(process.create_time() - value['created']) > .01:
            return None
        command = process.cmdline()
        if not command or not os.path.basename(command[0]).startswith('orn-agent'):
            return None
        if str(config_path()) not in command:
            return None
        return process
    except (OSError, ValueError, psutil.Error):
        return None


def managed():
    return owner() is not None


def _record(child):
    pid_path().parent.mkdir(mode=0o700, exist_ok=True)
    temporary = pid_path().with_suffix('.tmp')
    temporary.write_text(json.dumps({'pid': child.pid, 'created': psutil.Process(child.pid).create_time()}))
    temporary.replace(pid_path())


def _forget():
    try:
        pid_path().unlink()
    except OSError:
        pass


def _spawn():
    global ERROR, RESTARTS
    executable = binary()
    if not executable:
        raise RuntimeError('未找到 ORN Agent 二进制，请设置 ORH_ORN_BIN')
    with SPAWN:
        if probe():
            return owner()
        ensure_config()
        log = log_path()
        log.parent.mkdir(mode=0o700, exist_ok=True)
        with log.open('ab') as output:
            child = subprocess.Popen([str(executable), '-config', str(config_path())], cwd=str(ROOT),
                                     stdin=subprocess.DEVNULL, stdout=output, stderr=output, start_new_session=True)
        _record(child)
        with LOCK:
            RESTARTS += 1
        for _ in range(40):
            if child.poll() is not None:
                _forget()
                raise RuntimeError(f'ORN 进程退出，请查看 {log}')
            if probe():
                ERROR = ''
                return child
            time.sleep(.25)
        child.terminate()
        _forget()
        raise RuntimeError(f'ORN 未在 10 秒内就绪，请查看 {log}')


def start():
    try:
        _spawn()
    except RuntimeError as error:
        global ERROR
        with LOCK:
            ERROR = str(error)
    return status()


def supervise():
    delay = 5
    while not STOP.is_set():
        if STOP.wait(delay):
            return
        if not enabled():
            delay = 10
            continue
        if probe():
            delay = 5
            continue
        try:
            _spawn()
            delay = 5
        except RuntimeError:
            delay = min(delay * 2, 60)


def start_supervisor():
    global THREAD
    if THREAD and THREAD.is_alive():
        return status()
    STOP.clear()
    THREAD = threading.Thread(target=supervise, daemon=True, name='orn-supervisor')
    THREAD.start()
    return status()


def stop(timeout=10):
    process = owner()
    if process is None:
        _forget()
        return False
    try:
        process.send_signal(signal.SIGTERM)
        process.wait(timeout)
    except psutil.TimeoutExpired:
        try:
            process.kill()
        except psutil.Error:
            pass
    except psutil.Error:
        pass
    _forget()
    return True


def shutdown():
    STOP.set()
    thread = THREAD
    if thread and thread.is_alive():
        thread.join(5)
    stop()


def _systemctl(*arguments):
    return subprocess.run(['systemctl', '--user', *arguments], capture_output=True, text=True, timeout=30)


def standalone_service():
    """Describe the standalone ORN unit, if the host still has one and we did not take over."""
    global SERVICE_CACHE
    if TAKEOVER:
        return None
    stamp, cached = SERVICE_CACHE
    if time.monotonic() - stamp < 30:
        return cached
    found = None
    if sys.platform == 'darwin':
        plist = Path.home() / 'Library' / 'LaunchAgents' / 'top.openremotehub.orn.plist'
        loaded = plist.exists() and subprocess.run(
            ['launchctl', 'print', f'gui/{os.getuid()}/top.openremotehub.orn'], capture_output=True).returncode == 0
        found = ('launchd', plist) if loaded else None
    elif sys.platform == 'win32':
        try:
            result = subprocess.run(['schtasks', '/Query', '/TN', 'OpenRemoteHub ORN'], capture_output=True, text=True, timeout=30)
            found = ('scheduled-task', None) if result.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            found = None
    else:
        try:
            result = _systemctl('is-enabled', 'orn-agent')
            found = ('systemd', None) if result.stdout.strip() == 'enabled' else None
        except (OSError, subprocess.SubprocessError):
            found = None
    SERVICE_CACHE = (time.monotonic(), found)
    return found


def disable_standalone():
    """Stop and disable the separately installed ORN service, once."""
    found = standalone_service()
    if not found:
        return '没有发现独立的 ORN 服务'
    kind, plist = found
    if kind == 'launchd':
        target = f'gui/{os.getuid()}'
        subprocess.run(['launchctl', 'bootout', target, str(plist)], capture_output=True, timeout=30)
        subprocess.run(['launchctl', 'disable', f'{target}/top.openremotehub.orn'], capture_output=True, timeout=30)
        return '已停止并禁用独立 ORN LaunchAgent'
    if kind == 'scheduled-task':
        subprocess.run(['schtasks', '/End', '/TN', 'OpenRemoteHub ORN'], capture_output=True, timeout=30)
        subprocess.run(['schtasks', '/Change', '/TN', 'OpenRemoteHub ORN', '/DISABLE'], capture_output=True, timeout=30)
        return '已停止并禁用独立 ORN 计划任务'
    _systemctl('disable', '--now', 'orn-agent')
    return '已停止并禁用独立 ORN systemd 服务'


def takeover():
    """Adopt an existing standalone ORN install without re-enrolling the device."""
    global TAKEOVER, NOTE, ERROR, SERVICE_CACHE
    if not binary():
        raise RuntimeError('未找到 ORN Agent 二进制，请先安装或设置 ORH_ORN_BIN')
    previous = disable_standalone()
    SERVICE_CACHE = (0.0, None)
    for _ in range(40):
        if not probe():
            break
        time.sleep(.25)
    with LOCK:
        TAKEOVER = True
        NOTE = previous
        ERROR = ''
    start()
    return status()


def read_config():
    return json.loads(config_path().read_text())


def config_view():
    value = read_config()
    publish = value.get('publish') or {}
    return dict(hostname=value.get('hostname', ''), control_url=value.get('control_url', ''),
                api_addr=value.get('api_addr', ''), state_dir=value.get('state_dir', ''),
                publish={str(port): target for port, target in publish.items()},
                path=str(config_path()))


def save_config(payload):
    """Edit the local ORN identity and published services, then apply them."""
    current = read_config()
    hostname = (payload.get('hostname') or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,62}', hostname):
        raise ValueError('设备名称只能包含字母、数字、点、下划线和连字符')
    control = (payload.get('control_url') or '').strip()
    parsed = urlsplit(control)
    if not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('控制服务需为完整 Origin，例如 https://hs.openremotehub.top')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost', '::1')):
        raise ValueError('控制服务需要 HTTPS')
    publish = payload.get('publish') or {}
    if not isinstance(publish, dict):
        raise ValueError('发布端口格式无效')
    cleaned = {}
    for key, target in publish.items():
        try:
            port = int(key)
            host, _, address = str(target).rpartition(':')
            remote = int(address)
        except (TypeError, ValueError):
            raise ValueError(f'发布端口 {key} 需要形如 8765=127.0.0.1:8765') from None
        if not 1 <= port <= 65535 or not 1 <= remote <= 65535:
            raise ValueError('端口范围须为 1–65535')
        try:
            address_value = ipaddress.ip_address(host)
        except ValueError:
            raise ValueError(f'发布目标 {target} 必须使用 loopback IP') from None
        if not address_value.is_loopback:
            raise ValueError(f'发布目标 {target} 必须使用 loopback IP')
        cleaned[str(port)] = f'{address_value.compressed}:{remote}'
    current['hostname'] = hostname
    current['control_url'] = control
    current['publish'] = cleaned
    temporary = config_path().with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(current, output, ensure_ascii=False, indent=2)
    temporary.replace(config_path())
    # A changed identity or control server needs a fresh connection, so restart.
    restart()
    return status()


def _restart_standalone():
    found = standalone_service()
    if not found:
        return
    kind, plist = found
    if kind == 'launchd':
        subprocess.run(['launchctl', 'kickstart', '-k', f'gui/{os.getuid()}/top.openremotehub.orn'], capture_output=True, timeout=30)
    elif kind == 'scheduled-task':
        subprocess.run(['schtasks', '/End', '/TN', 'OpenRemoteHub ORN'], capture_output=True, timeout=30)
        subprocess.run(['schtasks', '/Run', '/TN', 'OpenRemoteHub ORN'], capture_output=True, timeout=30)
    else:
        _systemctl('restart', 'orn-agent')


def restart():
    """Restart the ORN process this install owns, or the standalone unit."""
    if managed():
        stop()
        for _ in range(40):
            if not probe():
                break
            time.sleep(.25)
        start()
    elif standalone_service():
        _restart_standalone()
        for _ in range(40):
            if probe():
                break
            time.sleep(.25)
    else:
        start()
    return status()


def status():
    process = owner()
    service = standalone_service()
    return dict(available=binary() is not None, enabled=enabled(), running=probe(),
                managed=process is not None, standalone=service[0] if service else '',
                takeover=TAKEOVER, note=NOTE, error=ERROR,
                pid=process.pid if process else None, restarts=RESTARTS,
                binary=str(binary()) if binary() else '', config=str(config_path()),
                token_file=str(token_path()), log=str(log_path()))
