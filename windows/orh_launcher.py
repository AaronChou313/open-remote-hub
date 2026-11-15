"""OpenRemoteHub for Windows: tray app, single instance, auto-update."""
import json
import os
import runpy
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APP = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'OpenRemoteHub'
BUNDLE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
CREATE_NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0
URL = 'http://127.0.0.1:8765/'
RELEASES = 'https://api.github.com/repos/AaronChou313/open-remote-hub/releases/latest'
_MUTEX = None


def version():
    try:
        return (BUNDLE / 'version.txt').read_text(encoding='utf-8').strip()
    except OSError:
        return '0.0.0'


def install_files():
    stamp = APP / 'version.txt'
    if stamp.is_file() and stamp.read_text(encoding='utf-8').strip() == version() and (APP / 'app').is_dir():
        return
    APP.mkdir(parents=True, exist_ok=True)
    for name in ('app', 'static', 'scripts'):
        source = BUNDLE / name
        if source.is_dir():
            shutil.copytree(source, APP / name, dirs_exist_ok=True)
    mesh = BUNDLE / 'bin' / 'orh-mesh.exe'
    if mesh.is_file():
        (APP / 'bin').mkdir(exist_ok=True)
        shutil.copy2(mesh, APP / 'bin' / 'orh-mesh.exe')
    env = APP / '.env'
    if not env.exists():
        addresses = set()
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                addresses.add(info[4][0])
        except OSError:
            pass
        addresses = {ip for ip in addresses if not ip.startswith('127.') and ip != '0.0.0.0'}
        env.write_text('ORH_HOST=0.0.0.0\nORH_PORT=8765\nORH_ALLOWED_HOSTS=' + ','.join(sorted(addresses)) + '\nORH_DSH_ENABLED=0\n', encoding='utf-8')
    stamp.write_text(version(), encoding='utf-8')


def healthy():
    try:
        with urllib.request.urlopen(URL + 'api/auth/status', timeout=1) as response:
            return response.status == 200
    except OSError:
        return False


def serve():
    install_files()
    runtime = APP / '.runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / 'server.pid').write_text(str(os.getpid()), encoding='ascii')
    os.chdir(APP)
    sys.path.insert(0, str(APP))
    if sys.stdout is None:
        log = open(runtime / 'server.log', 'a', encoding='utf-8', buffering=1)
        sys.stdout, sys.stderr = log, log
    try:
        runpy.run_path(str(APP / 'scripts' / 'server_windows.py'), run_name='__main__')
    finally:
        try:
            (runtime / 'server.pid').unlink()
        except OSError:
            pass


def kill(pid_file):
    path = APP / '.runtime' / pid_file
    if not path.is_file():
        return
    try:
        os.kill(int(path.read_text().strip()), 15)
    except (ValueError, OSError):
        pass
    try:
        path.unlink()
    except OSError:
        pass


def stop_children():
    kill('server.pid')
    try:
        import psutil
        for process in psutil.process_iter(['exe']):
            if process.info.get('exe') == str(APP / 'bin' / 'orh-mesh.exe'):
                process.terminate()
    except Exception:
        pass


def stop():
    kill('tray.pid')
    stop_children()


def single_instance():
    global _MUTEX
    if sys.platform != 'win32':
        return False
    import ctypes
    _MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, 'OpenRemoteHub.Tray')
    return ctypes.windll.kernel32.GetLastError() == 183


def ensure_server():
    if healthy():
        return None
    process = subprocess.Popen([sys.executable, '--serve'], cwd=str(APP), creationflags=CREATE_NO_WINDOW, close_fds=True)
    for _ in range(80):
        if healthy():
            break
        time.sleep(0.5)
    return process


def newer(candidate, current):
    left = [int(part) for part in candidate.split('.') if part.isdigit()]
    right = [int(part) for part in current.split('.') if part.isdigit()]
    for index in range(max(len(left), len(right))):
        a = left[index] if index < len(left) else 0
        b = right[index] if index < len(right) else 0
        if a != b:
            return a > b
    return False


def latest():
    request = urllib.request.Request(RELEASES, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'ORH-Windows/' + version()})
    with urllib.request.urlopen(request, timeout=12) as response:
        data = json.load(response)
    tag = str(data.get('tag_name', '')).lstrip('vV')
    if not tag or not newer(tag, version()):
        return None
    for asset in data.get('assets', []):
        name = asset.get('name', '')
        if name.startswith('ORH-Setup-') and name.endswith('.exe'):
            return {'version': tag, 'url': asset['browser_download_url']}
    return None


def apply_update(release):
    target = Path(tempfile.gettempdir()) / ('ORH-Setup-' + release['version'] + '.exe')
    urllib.request.urlretrieve(release['url'], target)
    installed = Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'OpenRemoteHub' / 'OpenRemoteHub.exe'
    stop_children()
    # A running exe cannot replace itself: hand the install to a detached
    # helper that waits for this process to exit, then upgrades and restarts.
    helper = Path(tempfile.gettempdir()) / 'orh-update.cmd'
    helper.write_text('@echo off\r\n:wait\r\ntasklist /FI "PID eq ' + str(os.getpid()) + '" 2>nul | find "' + str(os.getpid()) + '" >nul\r\nif not errorlevel 1 (timeout /t 1 /nobreak >nul & goto wait)\r\n"' + str(target) + '" /SILENT /CLOSEAPPLICATIONS /NORESTART\r\nstart "" "' + str(installed) + '"\r\ndel "%~f0"\r\n', encoding='ascii')
    subprocess.Popen(['cmd', '/c', str(helper)], creationflags=CREATE_NO_WINDOW, close_fds=True)


def tray():
    import pystray
    from PIL import Image
    install_files()
    (APP / '.runtime').mkdir(parents=True, exist_ok=True)
    (APP / '.runtime' / 'tray.pid').write_text(str(os.getpid()), encoding='ascii')
    pending = {}

    def open_console(icon=None, item=None):
        webbrowser.open(URL)

    def check(icon, item=None):
        threading.Thread(target=notify_available, args=(icon,), daemon=True).start()

    def notify_available(icon):
        try:
            release = latest()
        except Exception:
            if icon:
                icon.notify('检查更新失败，请稍后再试')
            return
        if release:
            icon.notify('发现新版本 ' + release['version'] + '，可在托盘菜单「安装更新」')
            try:
                icon.update_menu()
            except Exception:
                pass
        else:
            icon.notify('当前已是最新版本 ' + version())

    def install(icon, item):
        try:
            release = latest()
        except Exception:
            icon.notify('检查更新失败，请稍后再试')
            return
        if not release:
            icon.notify('当前已是最新版本 ' + version())
            return
        pending['release'] = release
        icon.stop()

    def shutdown(icon, item):
        icon.stop()

    image = Image.open(BUNDLE / 'static' / 'orh-logo.png').convert('RGBA').resize((64, 64))
    menu = pystray.Menu(
        pystray.MenuItem('打开控制台', open_console, default=True),
        pystray.MenuItem('检查更新', check),
        pystray.MenuItem('安装更新', install),
        pystray.MenuItem('停止并退出', shutdown),
    )
    icon = pystray.Icon('OpenRemoteHub', image, 'OpenRemoteHub ' + version(), menu)
    ensure_server()
    threading.Thread(target=notify_available, args=(icon,), daemon=True).start()
    icon.run()
    stop_children()
    if pending.get('release'):
        apply_update(pending['release'])


def main():
    arguments = sys.argv[1:]
    if '--stop' in arguments:
        stop()
        return
    if '--serve' in arguments:
        serve()
        return
    if single_instance():
        webbrowser.open(URL)
        return
    install_files()
    tray()


if __name__ == '__main__':
    main()
