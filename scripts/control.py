import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit
import psutil
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from app.main import PORT, NETWORK
LOCAL_URL=NETWORK.local_url(PORT)
tls_handlers=[]
if os.environ.get('ORH_TLS_CERT_FILE'):
    import ssl
    context=ssl.create_default_context(cafile=os.environ['ORH_TLS_CERT_FILE'])
    context.check_hostname=False
    if hasattr(ssl,'VERIFY_X509_PARTIAL_CHAIN'):context.verify_flags|=ssl.VERIFY_X509_PARTIAL_CHAIN
    tls_handlers.append(urllib.request.HTTPSHandler(context=context))
local_http=urllib.request.build_opener(urllib.request.ProxyHandler({}),*tls_handlers)
state=ROOT/'.runtime/server.json'
def process():
    try:
        d=json.loads(state.read_text());p=psutil.Process(d['pid'])
        if p.status()!=psutil.STATUS_ZOMBIE and abs(p.create_time()-d['created'])<.01 and str(ROOT/'scripts/server.py') in p.cmdline():return p
    except (OSError,ValueError,psutil.Error):pass
    return None
cmd=sys.argv[1]
# If our exact per-user LaunchAgent is installed, manage that job explicitly.
if sys.platform=='darwin':
    import plistlib
    job=Path.home()/'Library/LaunchAgents/local.openremotehub.plist'
    if job.exists():
        with job.open('rb') as f:configuration=plistlib.load(f)
        if configuration.get('ProgramArguments')==[str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/server.py')]:
            target=f'gui/{os.getuid()}'
            label=target+'/local.openremotehub'
            loaded=subprocess.run(['launchctl','print',label],capture_output=True).returncode==0
            if cmd=='stop':
                if loaded:subprocess.run(['launchctl','bootout',target,str(job)],check=True)
                print('Console stopped; existing terminal sessions and tasks remain running.')
            elif cmd=='start':
                if not loaded:subprocess.run(['launchctl','bootstrap',target,str(job)],check=True)
                for _ in range(100):
                    try:
                        with local_http.open(LOCAL_URL,timeout=1) as r:
                            if r.status==200:break
                    except OSError:time.sleep(.1)
                else:raise SystemExit('LaunchAgent readiness timed out; inspect .runtime/launchd.log')
                print(f'OpenRemoteHub (launchd): {LOCAL_URL}')
            else:print('LaunchAgent loaded' if loaded else 'LaunchAgent stopped')
            raise SystemExit(0)
p=process()
if cmd=='start':
    if p:
        print(f'Already running: {LOCAL_URL}');sys.exit()
    import socket
    try:
        with socket.create_connection((urlsplit(LOCAL_URL).hostname,PORT),timeout=.5):
            raise SystemExit(f'Port {PORT} already occupied; no process changed')
    except OSError:pass
    with (ROOT/'.runtime/server.log').open('ab') as log:
        child=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/server.py')],cwd=ROOT,stdout=log,stderr=log,stdin=subprocess.DEVNULL,start_new_session=True)
    state.write_text(json.dumps(dict(pid=child.pid,created=psutil.Process(child.pid).create_time())))
    for _ in range(50):
        if child.poll() is not None:raise SystemExit('Start failed. See .runtime/server.log')
        try:
            with local_http.open(LOCAL_URL,timeout=1) as response:
                if response.status==200:
                    print(f'OpenRemoteHub: {LOCAL_URL}');break
        except OSError:time.sleep(.1)
    else:raise SystemExit('Readiness timed out. See .runtime/server.log')
elif cmd=='stop':
    if p:
        p.send_signal(signal.SIGTERM)
        try:p.wait(20)
        except psutil.TimeoutExpired:raise SystemExit('Still stopping; not force-killed')
        state.unlink(missing_ok=True);print('Stopped console. Existing tasks and terminal sessions remain running.')
    else:print('No console process owned by this script')
else:print(f'PID {p.pid}' if p else 'Stopped')
