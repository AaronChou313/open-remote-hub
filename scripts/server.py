"""Foreground entry used by launchd, systemd, and the local lifecycle script."""
import os
import sys
from pathlib import Path
root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root))
os.chdir(root)
from app.main import PORT, NETWORK
import uvicorn
# Do not trust client-supplied forwarding headers. TLS termination needs an
# explicitly trusted proxy design rather than implicit X-Forwarded-* support.
uvicorn.run('app.main:app',host=NETWORK.bind,port=PORT,log_level='info',access_log=False,timeout_graceful_shutdown=5,ws='websockets-sansio',proxy_headers=False)
