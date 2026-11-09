"""Desktop VS Code links. The browser opens its own client over Remote SSH."""
import getpass
import ipaddress
import os
import re
from urllib.parse import quote
from fastapi import HTTPException, Request


def folder_url(request:Request,path:str):
    authority=os.environ.get('ORH_VSCODE_SSH_AUTHORITY','').strip()
    if not authority:
        user=os.environ.get('ORH_SSH_USER',getpass.getuser()).strip()
        authority=user+'@'+request.url.hostname
    parts=authority.split('@')
    host=parts[-1]
    valid_user=len(parts)==1 or (len(parts)==2 and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*',parts[0]))
    try:
        ipaddress.ip_address(host)
        valid_host=True
    except ValueError:
        valid_host=bool(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*',host))
    if len(authority)>255 or not valid_user or not valid_host:
        raise HTTPException(503,'VS Code SSH 地址无效，请检查 ORH_VSCODE_SSH_AUTHORITY / ORH_SSH_USER')
    return 'vscode://vscode-remote/ssh-remote+'+quote(authority,safe='@')+quote(path.rstrip('/')+'/',safe='/')
