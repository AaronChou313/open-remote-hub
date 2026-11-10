#!/usr/bin/env python3
"""Install only RemoteHub's dedicated proxy. Never stops or edits Clash."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import pwd
import shutil
import subprocess
import sys
import time
import socket as sockets
import http.client
import urllib.request

ROOT=Path(__file__).resolve().parent.parent
DATA=ROOT/'.runtime/proxy'
LABEL='local.openremotehub.proxy'


def download():
    machine={'arm64':'arm64','aarch64':'arm64','x86_64':'amd64'}.get(platform.machine())
    system={'Darwin':'darwin','Linux':'linux'}.get(platform.system())
    if not machine or not system:raise SystemExit('Unsupported architecture')
    req=urllib.request.Request('https://api.github.com/repos/MetaCubeX/mihomo/releases/latest',headers={'User-Agent':'OpenRemoteHub-setup'})
    release=json.load(urllib.request.urlopen(req,timeout=30))
    name='mihomo-'+system+'-'+machine+'-'+release['tag_name']+'.gz'
    asset=next((a for a in release['assets'] if a['name']==name),None)
    if not asset:raise SystemExit('Official release asset not found')
    raw=urllib.request.urlopen(asset['browser_download_url'],timeout=60).read()
    if asset.get('digest')!='sha256:'+hashlib.sha256(raw).hexdigest():raise SystemExit('Official archive digest missing or mismatched')
    folder=DATA/'bin';folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    binary=folder/'mihomo';binary.write_bytes(gzip.decompress(raw));binary.chmod(0o755)
    (folder/'release.json').write_text(json.dumps(dict(version=release['tag_name'],asset=name,binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),archive_digest=asset['digest'],source=release['html_url'])))
    print('Verified official Mihomo',release['tag_name'])


def run(argv):
    result=subprocess.run(argv,capture_output=True,text=True)
    if result.returncode:raise SystemExit((result.stderr or result.stdout).strip())


def connection(socket,uid):
    from proxy_engine import atomic
    atomic(DATA/'connection.json',{'socket':str(socket)})
    if os.geteuid()==0:os.chown(DATA/'connection.json',uid,-1)


def broker(socket,method,path,body=None):
    class LocalHTTP(http.client.HTTPConnection):
        def connect(self):
            self.sock=sockets.socket(sockets.AF_UNIX);self.sock.settimeout(50);self.sock.connect(str(socket))
    c=LocalHTTP('localhost')
    try:
        c.request(method,path,body=json.dumps(body) if body else None,headers={'Content-Type':'application/json'})
        response=c.getresponse();value=json.loads(response.read())
        if response.status>=400:raise ValueError(value.get('detail','Proxy operation failed'))
        return value
    finally:c.close()


def wait_ready(socket):
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        try:
            state=broker(socket,'GET','/orh/state')
            if state['ready']:return state
        except (OSError,ValueError):pass
        time.sleep(.2)
    raise SystemExit('Proxy service did not become ready; inspect the runner log. Clash was not changed.')


def launchd(home,binary,socket,uid,preview):
    label=LABEL+('.preview' if preview else '')
    runner=ROOT/'scripts/proxy_engine.py' if preview else home/'proxy_engine.py'
    domain='gui/'+str(uid) if preview else 'system'
    path=Path(pwd.getpwuid(uid).pw_dir)/'Library/LaunchAgents'/(label+'.plist') if preview else Path('/Library/LaunchDaemons')/(label+'.plist')
    cfg=dict(Label=label,ProgramArguments=['/usr/bin/python3',str(runner),'--home',str(home/'engine'),'--binary',str(binary),'--socket',str(socket),'--uid',str(uid)],RunAtLoad=True,KeepAlive=True,ThrottleInterval=10,StandardOutPath=str(home/'runner.log'),StandardErrorPath=str(home/'runner.log'),Umask=0o077)
    if path.exists():
        old=plistlib.loads(path.read_bytes())
        if old.get('Label')!=label or old.get('ProgramArguments',[None,None])[1]!=str(runner):raise SystemExit('Existing service is not owned by this installer')
        subprocess.run(['launchctl','bootout',domain,str(path)],capture_output=True)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(plistlib.dumps(cfg));path.chmod(0o644 if not preview else 0o600)
    run(['launchctl','bootstrap',domain,str(path)])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['download','stage','install'])
    parser.add_argument('--owner',default=os.environ.get('SUDO_USER') or pwd.getpwuid(os.getuid()).pw_name)
    args=parser.parse_args()
    DATA.mkdir(mode=0o700,parents=True,exist_ok=True)
    if args.action=='download':download();return
    binary=DATA/'bin/mihomo';metadata=DATA/'bin/release.json'
    if not binary.exists() or not metadata.exists():raise SystemExit('Run download first')
    if hashlib.sha256(binary.read_bytes()).hexdigest()!=json.loads(metadata.read_text())['binary_sha256']:raise SystemExit('Binary changed since verification')
    owner=pwd.getpwnam(args.owner)
    if args.action=='stage':
        if sys.platform!='darwin':raise SystemExit('For Linux, install the provided systemd unit instead')
        if os.geteuid()==0:raise SystemExit('Stage as the ordinary user')
        existing=DATA/'connection.json'
        if existing.exists():
            current=json.loads(existing.read_text()).get('socket','')
            if current and Path(current).exists() and current!=str(DATA/'preview.sock'):
                raise SystemExit('Dedicated system service is already installed; use proxyctl.py status instead of staging another core')
        socket=DATA/'preview.sock'
        launchd(DATA,binary,socket,owner.pw_uid,True)
        wait_ready(socket)
        connection(socket,owner.pw_uid)
        print('Preview service installed. TUN and system proxy remain OFF.')
        return
    if os.geteuid()!=0:raise SystemExit('Install requires sudo once. Clash remains connected.')
    if sys.platform=='darwin':
        home=Path('/Library/Application Support/OpenRemoteHubProxy')
        socket=Path('/var/run/openremotehub-proxy.sock')
        preview=Path(owner.pw_dir)/'Library/LaunchAgents'/(LABEL+'.preview.plist')
        if preview.exists():
            cfg=plistlib.loads(preview.read_bytes())
            if cfg.get('ProgramArguments',[None,None])[1]!=str(ROOT/'scripts/proxy_engine.py'):raise SystemExit('Unknown preview service')
            subprocess.run(['launchctl','bootout','gui/'+str(owner.pw_uid),str(preview)],capture_output=True)
            preview.unlink()
        installed=Path('/Library/LaunchDaemons')/(LABEL+'.plist')
        if installed.exists():
            cfg=plistlib.loads(installed.read_bytes())
            if cfg.get('ProgramArguments',[None,None])[1]!=str(home/'proxy_engine.py'):raise SystemExit('Unknown system proxy service; not changed')
            subprocess.run(['launchctl','bootout','system',str(installed)],capture_output=True)
    elif sys.platform=='linux':
        home=Path('/opt/openremotehub-proxy');socket=Path('/run/openremotehub-proxy.sock')
        installed=Path('/etc/systemd/system/openremotehub-proxy.service')
        if installed.exists():
            if 'ExecStart=/usr/bin/python3 /opt/openremotehub-proxy/proxy_engine.py ' not in installed.read_text():raise SystemExit('Unknown system proxy service; not changed')
            run(['systemctl','stop','openremotehub-proxy.service'])
    else:raise SystemExit('Unsupported OS')
    home.mkdir(mode=0o755,parents=True,exist_ok=True)
    if home.is_symlink() or home.stat().st_uid!=0:raise SystemExit('Service installation directory must be root-owned')
    shutil.copyfile(binary,home/'mihomo');(home/'mihomo').chmod(0o755)
    shutil.copyfile(ROOT/'scripts/proxy_engine.py',home/'proxy_engine.py');(home/'proxy_engine.py').chmod(0o644)
    if sys.platform=='darwin':launchd(home,home/'mihomo',socket,owner.pw_uid,False)
    else:
        unit='''[Unit]
Description=OpenRemoteHub Mihomo broker
After=network-online.target
[Service]
ExecStart=/usr/bin/python3 /opt/openremotehub-proxy/proxy_engine.py --home /opt/openremotehub-proxy/engine --binary /opt/openremotehub-proxy/mihomo --socket /run/openremotehub-proxy.sock --uid %d
Restart=on-failure
UMask=0077
[Install]
WantedBy=multi-user.target
'''%owner.pw_uid
        Path('/etc/systemd/system/openremotehub-proxy.service').write_text(unit)
        run(['systemctl','daemon-reload']);run(['systemctl','enable','--now','openremotehub-proxy.service'])
    connection(socket,owner.pw_uid)
    state=wait_ready(socket)
    # Carry only a profile explicitly selected in RemoteHub, never read Clash data.
    library=DATA/'profiles.json'
    if library.exists():
        rows=json.loads(library.read_text());active=next((x for x in rows['profiles'] if x['id']==rows['active']),None)
        if active and state['config_revision']!=__import__('proxy_engine').digest(active['source']):
            broker(socket,'POST','/orh/control',{'action':'apply','source':active['source'],'revision':state['revision']})
    print('Installed dedicated proxy service. New installation is idle; Clash was not stopped.')


if __name__=='__main__':main()
