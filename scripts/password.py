#!/usr/bin/env python3
"""Local recovery/setup: never pass passwords as command-line arguments."""
import getpass
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
if sys.platform=='win32':
    from app.windows_compat import install
    install()
    if sys.stdin is None:
        import ctypes
        if not ctypes.windll.kernel32.AttachConsole(-1):ctypes.windll.kernel32.AllocConsole()
        sys.stdin=open('CONIN$','r')
        sys.stdout=open('CONOUT$','w',buffering=1)
        sys.stderr=sys.stdout
if getattr(sys, 'frozen', False):
    from app.launcher import APP
    os.environ.setdefault('ORH_DATA_DIR',str(APP/'.runtime'))
    os.environ.setdefault('ORH_CONFIG_FILE',str(APP/'.env'))
from app import passwords, agent_settings

if __name__ == '__main__':
    password = getpass.getpass('New RemoteHub password: ')
    if password != getpass.getpass('Repeat password: '):
        raise SystemExit('Passwords differ; nothing changed.')
    passwords.save(password)
    if '--recovery' in sys.argv:
        value=agent_settings.load();value['recovery_enabled']=True;agent_settings.save(value)
    print('Local password saved.' + (' Cloud-independent recovery enabled.' if '--recovery' in sys.argv else ''))
