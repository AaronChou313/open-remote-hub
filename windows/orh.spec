# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('app', 'app'), ('static', 'static'), ('scripts', 'scripts'), ('bin', 'bin'), ('windows/version.txt', '.')]
hiddenimports = [
    'uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan.on',
]
for package in ('fastapi', 'uvicorn', 'starlette', 'pydantic', 'httpx', 'psutil', 'websockets', 'yaml', 'anyio'):
    try:
        collected, binaries, imports = collect_all(package)
        datas += collected
        hiddenimports += imports
    except Exception:
        pass

a = Analysis(['windows/orh_launcher.py'], pathex=[], binaries=[], datas=datas,
             hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='OpenRemoteHub', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='OpenRemoteHub')
