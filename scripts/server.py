"""Foreground entry used by launchd, systemd, and the local lifecycle script."""
import os
import sys
from pathlib import Path
root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root))
os.chdir(root)
from app.main import PORT, NETWORK
import uvicorn
# Both listeners share one lifecycle; DSH's native host remains an independent
# loopback process so closing the console never ends its current agent work.
from app.main import app
from app.dsh import settings
from app import mesh_runtime
cert = os.environ.get('ORH_TLS_CERT_FILE')
key = os.environ.get('ORH_TLS_KEY_FILE')
if bool(cert) != bool(key):
    raise SystemExit('ORH_TLS_CERT_FILE 和 ORH_TLS_KEY_FILE 必须同时配置')
tls = dict(ssl_certfile=cert, ssl_keyfile=key) if cert else {}
cfg=settings()
# One ORH install owns the ORN data plane; this foreground entry starts and reaps it.
mesh_runtime.start_supervisor()
try:
    from app import main
    from app.dsh_gateway import Dispatch
    ports=list(dict.fromkeys((PORT,cfg['gateway_port'])))
    sockets,main.LISTEN_ERRORS=NETWORK.listeners(ports)
    for error in main.LISTEN_ERRORS:print(error,flush=True)
    try:
        application=Dispatch(app,cfg['gateway_port']) if cfg['gateway_port']!=PORT else app
        config=uvicorn.Config(application,log_level='info',access_log=False,timeout_graceful_shutdown=5,ws='websockets-sansio',proxy_headers=False,**tls)
        uvicorn.Server(config).run(sockets=sockets)
    finally:
        for listener in sockets:listener.close()
finally:
    mesh_runtime.shutdown()
