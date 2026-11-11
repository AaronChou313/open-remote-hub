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
cert = os.environ.get('ORH_TLS_CERT_FILE')
key = os.environ.get('ORH_TLS_KEY_FILE')
if bool(cert) != bool(key):
    raise SystemExit('ORH_TLS_CERT_FILE 和 ORH_TLS_KEY_FILE 必须同时配置')
tls = dict(ssl_certfile=cert, ssl_keyfile=key) if cert else {}
cfg=settings()
if cfg['enabled']:
    import socket
    from app.dsh_gateway import Dispatch
    sockets=[]
    try:
        for port in (PORT,cfg['gateway_port']):
            address=NETWORK.bind
            family=socket.AF_INET6 if ':' in address else socket.AF_INET
            sock=socket.socket(family,socket.SOCK_STREAM)
            sockets.append(sock);sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            sock.bind((address,port));sock.set_inheritable(True)
        config=uvicorn.Config(Dispatch(app,cfg['gateway_port']),log_level='info',access_log=False,timeout_graceful_shutdown=5,ws='websockets-sansio',proxy_headers=False,**tls)
        uvicorn.Server(config).run(sockets=sockets)
    finally:
        for sock in sockets:sock.close()
else:
    uvicorn.run(app,host=NETWORK.bind,port=PORT,log_level='info',access_log=False,timeout_graceful_shutdown=5,ws='websockets-sansio',proxy_headers=False,**tls)
