"""Foreground entry used by launchd, systemd, and the local lifecycle script."""
import os
import sys
from pathlib import Path
root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root))
os.chdir(root)
from app.main import PORT
import uvicorn
# Deliberately hard-code loopback until a separate remote security design exists.
if os.environ.get('ORH_HOST','127.0.0.1')!='127.0.0.1':
    raise SystemExit('Only ORH_HOST=127.0.0.1 is supported. Use SSH forwarding for remote access.')
uvicorn.run('app.main:app',host='127.0.0.1',port=PORT,log_level='info',access_log=False,timeout_graceful_shutdown=5,ws='websockets-sansio')
