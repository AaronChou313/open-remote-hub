"""Explicitly invoked installer; never touches any other launchd job."""
import os
import argparse
from pathlib import Path
import plistlib
import subprocess
import sys
root=Path(__file__).resolve().parent.parent
label='local.openremotehub'
path=Path.home()/'Library/LaunchAgents'/f'{label}.plist'
target=f'gui/{os.getuid()}'
if sys.platform!='darwin':raise SystemExit('macOS only; see deploy/openremotehub.service for Ubuntu')
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('action',choices=['install','uninstall','render'])
action=parser.parse_args().action
if action=='uninstall':
    if path.exists():
        subprocess.run(['launchctl','bootout',target,str(path)],check=False)
        path.unlink()
    print('OpenRemoteHub LaunchAgent removed; data preserved.')
else:
    data=dict(Label=label,ProgramArguments=[str(root/'.venv/bin/python'),str(root/'scripts/server.py')],WorkingDirectory=str(root),RunAtLoad=True,KeepAlive=True,ThrottleInterval=10,StandardOutPath=str(root/'.runtime/launchd.log'),StandardErrorPath=str(root/'.runtime/launchd.log'),EnvironmentVariables=dict(PATH='/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',HOME=str(Path.home()),ORH_MANAGED_BY='launchd'))
    if action=='render':
        output=root/'.runtime/local.openremotehub.plist'
        output.write_bytes(plistlib.dumps(data))
        print(output)
        raise SystemExit(0)
    if path.exists():raise SystemExit('LaunchAgent already exists; inspect it before replacing')
    subprocess.run([str(root/'scripts/stop.sh')],check=True)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('wb') as f:plistlib.dump(data,f)
    subprocess.run(['launchctl','bootstrap',target,str(path)],check=True)
    print('Installed per-user LaunchAgent (starts after user login).')
