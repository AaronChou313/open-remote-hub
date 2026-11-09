"""Independent DSH log/auth supervisor: survives console restarts, logs no tokens.

Only the native process launch token is exchanged via DSH's official browser
login. No signing-secret extraction or cookie forgery. Native cookies stay in a
0600 file read by the authenticated RemoteHub gateway.
"""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from urllib.parse import urlsplit,parse_qs
import httpx

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from app.dsh_auth import exchange,save,redact
os.umask(0o077)
plan=json.loads(Path(sys.argv[1]).read_text())
port=plan['port'];data=Path(plan['data']);base=f'http://127.0.0.1:{port}'
env=dict(os.environ);env['DSH_HOME']=plan['home']
child=subprocess.Popen(plan['argv'],cwd=str(Path.home()),env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
def stop(signum,frame):
    if child.poll() is None:child.terminate()
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
paired=False
with (data/'dsh.log').open('a',encoding='utf-8') as log:
    for raw in iter(child.stdout.readline,b''):
        line=raw.decode('utf-8',errors='replace')
        if not paired:
            for candidate in re.findall(r'http://127\.0\.0\.1:\d+/[^\s\x1b<>"\']*',line):
                parsed=urlsplit(candidate);token=parse_qs(parsed.query).get('token',[])
                if parsed.netloc!=f'127.0.0.1:{port}' or parsed.path!='/' or len(token)!=1:continue
                for _ in range(10):
                    try:
                        save(data,exchange(port,token[0]));paired=True;break
                    except (httpx.HTTPError,RuntimeError):pass
                    time.sleep(.2)
        safe=redact(line)
        log.write(safe);log.flush()
child.stdout.close()
sys.exit(child.wait())
