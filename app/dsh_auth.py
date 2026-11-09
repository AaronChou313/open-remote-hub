"""Official DSH launch-token exchange, held exclusively on the local server."""
import json
import os
from pathlib import Path
import re
import secrets
import time
import httpx


def redact(line):return re.sub(r'([?&]token=)[^\s&\x1b<>"\']+',r'\1[redacted]',line)


def exchange(port,token):
    base=f'http://127.0.0.1:{port}'
    with httpx.Client(trust_env=False,timeout=3,follow_redirects=False) as c:
        r=c.get(base+'/',params={'token':token},headers={'Origin':base})
        cookie='; '.join(f'{k}={v}' for k,v in c.cookies.items())
        if r.status_code!=303 or not cookie:raise RuntimeError('DSH 本机认证失败')
        match=re.search(r'max-age=(\d+)',r.headers.get('set-cookie',''),re.I)
        age=int(match[1]) if match else 86400
        return dict(port=port,cookie=cookie,launch_token=token,renew_after=time.time()+max(1,age-min(86400,age//10)))


def save(folder,record):
    folder=Path(folder);temp=folder/('.dsh-auth-'+secrets.token_hex(8))
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w') as f:json.dump(record,f)
        temp.replace(folder/'dsh-auth.json')
    finally:temp.unlink(missing_ok=True)
