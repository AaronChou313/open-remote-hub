# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent

datas = [(str(ROOT / name), name) for name in ('app', 'static', 'scripts', 'bin')] + [(str(ROOT / 'windows' / 'version.txt'), '.')]
hiddenimports = [
    'uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan.on',
    'sqlite3', 'ssl', 'email', 'email.mime.text', 'http.client', 'http.cookiejar',
    'xml.etree.ElementTree', 'multiprocessing', 'ctypes',
    'app.main', 'app.mesh_runtime', 'app.cloud_agent', 'app.remote_connect.api',
    'app.remote_connect.tailscale', 'app.windows_compat', 'app.platforms',
    'app.network', 'app.dsh', 'app.dsh_gateway', 'app.discovery', 'app.passwords', 'app.access',
]
for package in ('fastapi', 'uvicorn', 'starlette', 'pydantic', 'httpx', 'psutil', 'websockets', 'yaml', 'anyio', 'pystray', 'PIL', 'six'):
    try:
        collected, binaries, imports = collect_all(package)
        datas += collected
        hiddenimports += imports
    except Exception:
        pass

a = Analysis([str(ROOT / 'windows' / 'orh_launcher.py')], pathex=[str(ROOT)], binaries=[], datas=datas,
             hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='OpenRemoteHub', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='OpenRemoteHub')
