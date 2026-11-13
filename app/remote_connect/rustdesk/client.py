import json
import os
import plistlib
import re
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import psutil
from .ipc import native, NativeError
from .settings import BINARY, data_dir, OPTIONS

lock = threading.RLock()
def autostart_path():
    return data_dir() / 'rustdesk-autostart.json'


def autostart():
    path = autostart_path()
    return json.loads(path.read_text()).get('enabled', False) if path.exists() else False


def set_autostart(enabled):
    temporary = data_dir() / 'rustdesk-autostart.tmp'
    temporary.write_text(json.dumps({'enabled': enabled}))
    temporary.chmod(0o600)
    temporary.replace(autostart_path())


def processes():
    result = []
    for process in psutil.process_iter(['pid', 'name', 'create_time', 'username']):
        if (process.info['name'] or '').lower() != 'rustdesk':
            continue
        try:
            executable = Path(process.exe())
            # Gatekeeper can run the existing app from an AppTranslocation
            # bundle even when the installed copy is in /Applications.
            native_bundle = executable.parts[-4:] == ('RustDesk.app', 'Contents', 'MacOS', BINARY.name)
            if (executable != BINARY and not native_bundle) or process.uids().real != os.getuid():
                continue
            args = process.cmdline()[1:]
            if any(flag in args for flag in ('--cm', '--get-id', '--option')):
                continue
            result.append(dict(pid=process.pid, created=process.create_time(), background='--server' in args))
        except psutil.Error:
            continue
    return result


def start():
    with lock:
        try:
            native.config('id')
            return dict(reused=True)
        except NativeError:
            if processes():
                raise NativeError('RustDesk 进程已存在，本机接口尚未就绪，请稍后刷新')
        if not BINARY.is_file():
            raise NativeError('未找到已安装的 RustDesk 客户端')
        with (data_dir() / 'rustdesk.log').open('ab') as output:
            subprocess.Popen([str(BINARY), '--server'], stdout=output, stderr=output,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        return dict(reused=False)


def watch(stop):
    while not stop.wait(5):
        try:
            if autostart():
                start()
        except (NativeError, OSError):
            # A live GUI may be starting. Its PID remains authoritative and the
            # next ordinary cycle checks readiness without launching duplicates.
            continue


def status():
    rows = processes()
    version = None
    info = BINARY.parents[1] / 'Info.plist'
    if info.exists():
        with info.open('rb') as stream:
            version = plistlib.load(stream).get('CFBundleShortVersionString')
    result = dict(installed=BINARY.is_file(), version=version, processes=rows,
                  autostart=autostart(), ready=False, device_id=None, online=False,
                  accepting=False, connections=None, permanent_password_set=None,
                  time=time.time())
    try:
        result['device_id'] = native.config('id')
        online = native.request('OnlineStatus')
        options = native.options()
        result.update(ready=True, online=bool(online and online[0] > 0),
                      key_confirmed=bool(online and online[1]), accepting=options.get('stop-service') != 'Y',
                      connections=native.request('VideoConnCount'),
                      permanent_password_set=native.config('permanent-password-set') == 'Y')
    except NativeError as error:
        result['message'] = str(error)
    return result


def settings():
    options = native.options()
    return {key: options.get(key, '') for key in OPTIONS}


def validate(key, value):
    if key not in OPTIONS or not isinstance(value, str) or len(value) > 1024 or any(ord(char) < 32 for char in value):
        raise ValueError('设置项或内容无效')
    kind, choices = OPTIONS[key]
    if kind == 'bool' and value not in ('Y', 'N', ''):
        raise ValueError('开关值无效')
    if kind == 'choice' and value not in choices:
        raise ValueError('请选择有效选项')
    if kind == 'port' and value and (not value.isdecimal() or not 1 <= int(value) <= 65535):
        raise ValueError('直连端口须为 1–65535')
    if kind == 'url' and value:
        url = urlsplit(value)
        if url.scheme not in ('http', 'https') or not url.hostname:
            raise ValueError('API 地址须为完整 HTTP / HTTPS 地址')
    return value


def update_settings(changes, before):
    for key, value in changes.items():
        validate(key, value)
    with lock:
        options = native.options()
        if any(key not in before or options.get(key, '') != before[key] for key in changes):
            raise ValueError('设置已在其他窗口更改，请刷新后再保存')
        for key, value in changes.items():
            if value:
                options[key] = value
            else:
                options.pop(key, None)
        if changes:
            native.set_options(options)
        result = settings()
        if any(result[key] != value for key, value in changes.items()):
            raise NativeError('RustDesk 设置未完整生效，请刷新核对')
        return result


def set_accepting(enabled):
    with lock:
        options = native.options()
        desired = '' if enabled else 'Y'
        if options.get('stop-service', '') != desired:
            if desired:
                options['stop-service'] = desired
            else:
                options.pop('stop-service', None)
            native.set_options(options)


def target(value):
    value = value.strip()
    if re.fullmatch(r'[0-9 ]+', value):
        value = value.replace(' ', '')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:@\[\]-]{0,253}', value):
        raise ValueError('请输入 RustDesk ID 或目标主机地址')
    return value


def connect(value, mode):
    value = target(value)
    if mode not in ('desktop', 'files'):
        raise ValueError('请选择桌面连接或文件传输')
    flag = '--connect' if mode == 'desktop' else '--file-transfer'
    with (data_dir() / 'rustdesk.log').open('ab') as output:
        subprocess.Popen([str(BINARY), flag, value], stdout=output, stderr=output,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    return dict(target=value, location='host', mode=mode)
