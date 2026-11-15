"""OpenRemoteHub for Windows: extract the app once, then serve or open it."""
import os
import runpy
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

APP = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'OpenRemoteHub'
BUNDLE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
CREATE_NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0
URL = 'http://127.0.0.1:8765/'


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


def stop():
    pid = APP / '.runtime' / 'server.pid'
    if pid.is_file():
        try:
            os.kill(int(pid.read_text().strip()), 15)
        except (ValueError, OSError):
            pass
        try:
            pid.unlink()
        except OSError:
            pass
    try:
        import psutil
        for process in psutil.process_iter(['name', 'exe']):
            if process.info.get('exe') == str(APP / 'bin' / 'orh-mesh.exe'):
                process.terminate()
    except Exception:
        pass


def main():
    arguments = sys.argv[1:]
    if '--stop' in arguments:
        stop()
        return
    if '--serve' in arguments:
        serve()
        return
    if not healthy():
        install_files()
        subprocess.Popen([sys.executable, '--serve'], cwd=str(APP), creationflags=CREATE_NO_WINDOW, close_fds=True)
        for _ in range(80):
            if healthy():
                break
            time.sleep(0.5)
    webbrowser.open(URL)


if __name__ == '__main__':
    main()
