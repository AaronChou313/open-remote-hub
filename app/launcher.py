"""Installed desktop lifecycle, tray, background Agent and native Client."""
import json
import platform
import plistlib
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
from pathlib import Path

APP = (Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'OpenRemoteHub' if sys.platform == 'win32' else Path.home() / 'Library/Application Support/OpenRemoteHub' if sys.platform == 'darwin' else Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'openremotehub')
APP = Path(os.environ.get('ORH_APP_DIR', str(APP)))
CONFIG = Path(os.environ.get('ORH_CONFIG_FILE', str(APP / '.env')))
for line in CONFIG.read_text(encoding='utf-8').splitlines() if CONFIG.exists() else []:
    if line and not line.startswith('#') and '=' in line:
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip())
BUNDLE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
CREATE_NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0
URL = 'http://127.0.0.1:' + os.environ.get('ORH_PORT', '8765') + '/'
RELEASES = 'https://api.github.com/repos/AaronChou313/open-remote-hub/releases/latest'
_MUTEX = None


def command(*arguments):
    if getattr(sys, 'frozen', False):
        return [sys.executable, *arguments]
    return [sys.executable, str(BUNDLE / 'desktop/main.py'), *arguments]


def asset_matches(name):
    if sys.platform == 'win32':
        return name.startswith('ORH-Setup-') and name.endswith('.exe')
    architecture = 'arm64' if platform.machine().lower() in ('arm64', 'aarch64') else 'amd64'
    suffix = f'macos-{architecture}.dmg' if sys.platform == 'darwin' else f'linux-{architecture}.deb'
    return name.endswith(suffix)


def setup_service():
    if not getattr(sys, 'frozen', False) or sys.platform == 'win32':
        return False
    runtime = APP / '.runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    if sys.platform == 'darwin':
        legacy = Path.home() / 'Library/LaunchAgents/local.openremotehub.plist'
        if legacy.exists():
            previous = plistlib.loads(legacy.read_bytes())
            arguments = previous.get('ProgramArguments') or []
            source = next((Path(value).parents[1] / '.runtime' for value in arguments if value.endswith('/scripts/server.py')), None)
            if source and not (runtime / 'instance-id').exists():
                for name in ('instance-id', 'cloud-binding.json', 'credentials.json', 'modules.json'):
                    if (source / name).is_file():
                        shutil.copy2(source / name, runtime / name)
            if source:
                for name in ('dsh-auth.json', 'dsh-process.json'):
                    if (source / name).is_file() and not (runtime / name).exists():
                        shutil.copy2(source / name, runtime / name)
                for name in ('connection.json', 'profiles.json'):
                    old = source / 'proxy' / name
                    target = runtime / 'proxy' / name
                    if old.is_file() and not target.exists():
                        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                        shutil.copy2(old, target)
            subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}', str(legacy)], capture_output=True)
            legacy.unlink()
        path = Path.home() / 'Library/LaunchAgents/top.openremotehub.agent.plist'
        value = dict(Label='top.openremotehub.agent', ProgramArguments=command('--serve'),
                     RunAtLoad=True, KeepAlive=True, WorkingDirectory=str(APP),
                     StandardOutPath=str(runtime / 'server.log'), StandardErrorPath=str(runtime / 'server.log'))
        previous = plistlib.loads(path.read_bytes()) if path.exists() else None
        if previous != value:
            subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}', str(path)], capture_output=True)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(plistlib.dumps(value))
        target = f'gui/{os.getuid()}/top.openremotehub.agent'
        loaded = subprocess.run(['launchctl', 'print', target], capture_output=True).returncode == 0
        if not loaded:
            subprocess.run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(path)], check=True)
            return 'started'
        return 'running'
    elif shutil.which('systemctl'):
        available = subprocess.run(['systemctl', '--user', 'show-environment'], capture_output=True).returncode == 0
        if available:
            active = subprocess.run(['systemctl', '--user', 'is-active', '--quiet', 'openremotehub.service'], capture_output=True).returncode == 0
            path = Path.home() / '.config/systemd/user/openremotehub.service'
            path.parent.mkdir(parents=True, exist_ok=True)
            executable = str(Path(sys.executable).resolve()).replace('"', '\\"')
            path.write_text('[Unit]\nDescription=OpenRemoteHub Agent\nAfter=network-online.target\n\n[Service]\nExecStart="' + executable + '" --serve\nRestart=on-failure\nRestartSec=3\n\n[Install]\nWantedBy=default.target\n')
            subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
            subprocess.run(['systemctl', '--user', 'enable', '--now', 'openremotehub.service'], check=True)
            return 'running' if active else 'started'
    return False


def stop_service():
    if sys.platform == 'darwin':
        path = Path.home() / 'Library/LaunchAgents/top.openremotehub.agent.plist'
        if path.exists():
            subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}', str(path)], capture_output=True)
    elif sys.platform.startswith('linux') and shutil.which('systemctl'):
        subprocess.run(['systemctl', '--user', 'stop', 'openremotehub.service'], capture_output=True)


def version():
    try:
        return (BUNDLE / 'VERSION').read_text(encoding='utf-8').strip()
    except OSError:
        return '0.0.0'


def install_files():
    stamp = APP / 'VERSION'
    if stamp.is_file() and stamp.read_text(encoding='utf-8').strip() == version() and (APP / 'app').is_dir():
        return
    APP.mkdir(parents=True, exist_ok=True)
    for name in ('app', 'static', 'scripts', 'config'):
        source = BUNDLE / name
        if source.is_dir():
            shutil.copytree(source, APP / name, dirs_exist_ok=True)
    mesh_name = 'orh-mesh.exe' if sys.platform == 'win32' else 'orh-mesh'
    mesh = BUNDLE / 'bin' / mesh_name
    if mesh.is_file():
        (APP / 'bin').mkdir(exist_ok=True)
        shutil.copy2(mesh, APP / 'bin' / mesh_name)
    env = APP / '.env'
    if not env.exists():
        addresses = set()
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                addresses.add(info[4][0])
        except OSError:
            pass
        addresses = {ip for ip in addresses if not ip.startswith('127.') and ip != '0.0.0.0'}
        env.write_text('ORH_HOST=127.0.0.1\nORH_PORT=8765\nORH_ALLOWED_HOSTS=' + ','.join(sorted(addresses)) + '\nORH_FILE_ROOTS=' + json.dumps([str(Path.home())], ensure_ascii=False) + '\nORH_DSH_ENABLED=0\n', encoding='utf-8')
    elif 'ORH_FILE_ROOTS' not in {line.split('=', 1)[0].strip() for line in env.read_text(encoding='utf-8').splitlines() if '=' in line}:
        with env.open('a', encoding='utf-8') as output:
            output.write('\nORH_FILE_ROOTS=' + json.dumps([str(Path.home())], ensure_ascii=False) + '\n')
    stamp.write_text(version(), encoding='utf-8')


def healthy():
    try:
        with urllib.request.urlopen(URL + 'api/auth/status', timeout=1) as response:
            return response.status == 200 and json.load(response).get('version') == version()
    except OSError:
        return False


def serve():
    install_files()
    os.environ['ORH_DATA_DIR'] = str(APP / '.runtime')
    os.environ['ORH_CONFIG_FILE'] = str(APP / '.env')
    if sys.platform == 'win32':
        import ctypes
        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, 'OpenRemoteHub.Server')
        if ctypes.windll.kernel32.GetLastError() == 183:
            return
        globals()['_SERVER_MUTEX'] = mutex
    runtime = APP / '.runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / 'server.pid').write_text(str(os.getpid()), encoding='ascii')
    os.chdir(APP)
    sys.path.insert(0, str(APP))
    if sys.stdout is None:
        log = open(runtime / 'server.log', 'a', encoding='utf-8', buffering=1)
        sys.stdout, sys.stderr = log, log
    try:
        entry = 'server_windows.py' if sys.platform == 'win32' else 'server.py'
        runpy.run_path(str(APP / 'scripts' / entry), run_name='__main__')
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
        name = 'orh-mesh.exe' if sys.platform == 'win32' else 'orh-mesh'
        owned = {(APP / 'bin' / name).resolve(), (BUNDLE / 'bin' / name).resolve()}
        for process in psutil.process_iter(['exe']):
            executable = process.info.get('exe')
            if executable and Path(executable).resolve() in owned:
                process.terminate()
    except Exception:
        pass


def stop():
    kill('client.pid')
    kill('tray.pid')
    stop_service()
    stop_children()


def restart_agent():
    import psutil
    path = APP / '.runtime/server.pid'
    process = psutil.Process(int(path.read_text())) if path.exists() else None
    stop_service()
    kill('server.pid')
    if process:
        try:
            process.wait(timeout=20)
        except psutil.NoSuchProcess:
            pass
    ensure_server()


def single_instance(name='Tray'):
    global _MUTEX
    if sys.platform != 'win32':
        return False
    import ctypes
    _MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, 'OpenRemoteHub.' + name)
    return ctypes.windll.kernel32.GetLastError() == 183


def ensure_server():
    if healthy():
        return None
    managed = setup_service()
    if managed:
        if managed == 'running' and sys.platform == 'darwin':
            subprocess.run(['launchctl', 'kickstart', '-k', f'gui/{os.getuid()}/top.openremotehub.agent'], check=True)
        elif managed == 'running':
            subprocess.run(['systemctl', '--user', 'restart', 'openremotehub.service'], check=True)
        for _ in range(80):
            if healthy():
                return None
            time.sleep(.5)
        raise RuntimeError('后台启动失败，请查看 ' + str(APP / '.runtime/server.log'))
    runtime = APP / '.runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / 'server.log').open('ab') as log:
        process = subprocess.Popen(command('--serve'), cwd=str(APP), creationflags=CREATE_NO_WINDOW, close_fds=True, start_new_session=sys.platform != 'win32', stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    for _ in range(80):
        if healthy():
            break
        time.sleep(0.5)
    if not healthy():
        raise RuntimeError('后台启动失败，请查看 ' + str(APP / '.runtime/server.log'))
    return process


def client():
    if single_instance('Client'):
        focus_client()
        return
    install_files()
    ensure_server()
    sys.path.insert(0, str(APP))
    from app.desktop_client import run
    runtime = APP / '.runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    pid = runtime / 'client.pid'
    pid.write_text(str(os.getpid()), encoding='ascii')
    try:
        run(URL + 'client', runtime / 'client-webview')
    finally:
        pid.unlink(missing_ok=True)


def focus_client():
    if sys.platform == 'win32':
        import ctypes
        window = ctypes.windll.user32.FindWindowW(None, 'OpenRemoteHub')
        if window:
            ctypes.windll.user32.ShowWindow(window, 9)
            ctypes.windll.user32.SetForegroundWindow(window)
            return True
    return False


def open_client():
    if focus_client():
        return
    subprocess.Popen(command('--client'), cwd=str(APP),
                     creationflags=CREATE_NO_WINDOW, close_fds=True)


def newer(candidate, current):
    left = [int(part) for part in candidate.split('.') if part.isdigit()]
    right = [int(part) for part in current.split('.') if part.isdigit()]
    for index in range(max(len(left), len(right))):
        a = left[index] if index < len(left) else 0
        b = right[index] if index < len(right) else 0
        if a != b:
            return a > b
    return False


def release_info():
    request = urllib.request.Request(RELEASES, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'OpenRemoteHub/' + version()})
    with urllib.request.urlopen(request, timeout=12) as response:
        data = json.load(response)
    tag = str(data.get('tag_name', '')).lstrip('vV')
    for asset in data.get('assets', []):
        name = asset.get('name', '')
        if tag and asset_matches(name):
            return {'version': tag, 'url': asset['browser_download_url'], 'name':name,
                    'size':asset.get('size',0), 'notes':data.get('body',''), 'page':data.get('html_url','https://github.com/AaronChou313/open-remote-hub/releases/latest')}
    raise RuntimeError('发行页面尚未提供当前平台的安装包')


def latest():
    release = release_info()
    return release if newer(release['version'], version()) else None


def apply_update(release, downloaded=None):
    target = Path(downloaded) if downloaded else Path(tempfile.gettempdir()) / release['name']
    if not downloaded:
        urllib.request.urlretrieve(release['url'], target)
    if sys.platform != 'win32':
        subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(target)], close_fds=True)
        return
    installed = Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'OpenRemoteHub' / 'OpenRemoteHub.exe'
    stop_children()
    # A running exe cannot replace itself: hand the install to a detached
    # helper that waits for this process to exit, then upgrades and restarts.
    helper = Path(tempfile.gettempdir()) / 'orh-update.cmd'
    helper.write_text('@echo off\r\nchcp 65001 >nul\r\n:wait\r\ntasklist /FI "PID eq ' + str(os.getpid()) + '" 2>nul | find "' + str(os.getpid()) + '" >nul\r\nif not errorlevel 1 (timeout /t 1 /nobreak >nul & goto wait)\r\n"' + str(target) + '" /SILENT /CLOSEAPPLICATIONS /NORESTART\r\nstart "" "' + str(installed) + '"\r\ndel "%~f0"\r\n', encoding='utf-8')
    subprocess.Popen(['cmd', '/c', str(helper)], creationflags=CREATE_NO_WINDOW, close_fds=True)


def tray(open_window=True):
    import pystray
    from PIL import Image
    install_files()
    (APP / '.runtime').mkdir(parents=True, exist_ok=True)
    (APP / '.runtime' / 'tray.pid').write_text(str(os.getpid()), encoding='ascii')
    def open_console(icon=None, item=None):
        open_client()

    def shutdown(icon, item):
        icon.stop()

    image = Image.open(BUNDLE / 'static' / 'orh-logo.png').convert('RGBA').resize((64, 64))
    menu = pystray.Menu(
        pystray.MenuItem('打开 OpenRemoteHub', open_console, default=True),
        pystray.MenuItem('停止后台并退出', shutdown),
    )
    icon = pystray.Icon('OpenRemoteHub', image, 'OpenRemoteHub ' + version(), menu)
    ensure_server()
    if open_window:
        open_client()
    icon.run()
    kill('client.pid')
    stop_service()
    stop_children()


def main():
    if sys.platform != 'win32':
        paths = [str(Path.home() / '.local/bin'), '/opt/homebrew/bin', '/usr/local/bin', os.environ.get('PATH', '/usr/bin:/bin')]
        os.environ['PATH'] = os.pathsep.join(paths)
    arguments = sys.argv[1:]
    if '--run-script' in arguments:
        index = arguments.index('--run-script')
        name = arguments[index + 1]
        if Path(name).name != name or not name.endswith('.py'):
            raise SystemExit('无效的内置脚本')
        script = BUNDLE / 'scripts' / name
        sys.argv = [str(script), *arguments[index + 2:]]
        sys.path.insert(0, str(script.parent))
        runpy.run_path(str(script), run_name='__main__')
        return
    if '--cwd-exec' in arguments:
        index = arguments.index('--cwd-exec')
        os.fchdir(int(arguments[index + 1]))
        target = arguments[index + 2:]
        os.execvpe(target[0], target, os.environ)
    if '--restart-app' in arguments:
        stop()
        subprocess.Popen(command(), creationflags=CREATE_NO_WINDOW, close_fds=True)
        return
    if '--install-update' in arguments:
        target = Path(arguments[arguments.index('--install-update') + 1])
        if target.parent != Path(tempfile.gettempdir()) / 'orh-updates' or not asset_matches(target.name):
            raise SystemExit('无效的更新安装包')
        if sys.platform == 'win32':
            stop()
        apply_update({'name': target.name}, downloaded=target)
        return
    if '--restart-agent' in arguments:
        restart_agent()
        return
    if '--headless' in arguments:
        install_files()
        ensure_server()
        return
    if '--stop' in arguments:
        stop()
        return
    if '--serve' in arguments:
        serve()
        return
    if '--client' in arguments:
        client()
        return
    if single_instance():
        if '--tray' not in arguments:
            open_client()
        return
    install_files()
    tray(open_window='--tray' not in arguments)


if __name__ == '__main__':
    main()
