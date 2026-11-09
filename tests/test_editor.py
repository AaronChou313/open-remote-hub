import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import pytest
from fastapi import HTTPException, Request
from app.editor import folder_url


def test_vscode_authority_follows_browser_host_and_supports_client_alias(monkeypatch):
    request=Request({'type':'http','scheme':'http','server':('100.66.1.4',8765),'path':'/','headers':[]})
    monkeypatch.delenv('ORH_VSCODE_SSH_AUTHORITY',raising=False)
    monkeypatch.setenv('ORH_SSH_USER','fixture-user')
    assert folder_url(request,'/Users/fixture/Projects')=='vscode://vscode-remote/ssh-remote+fixture-user@100.66.1.4/Users/fixture/Projects/'
    monkeypatch.setenv('ORH_VSCODE_SSH_AUTHORITY','mac-mini')
    assert folder_url(request,'/')=='vscode://vscode-remote/ssh-remote+mac-mini/'
    monkeypatch.setenv('ORH_VSCODE_SSH_AUTHORITY','user@host?bad=1')
    with pytest.raises(HTTPException):folder_url(request,'/')


def test_vscode_link_accepts_ipv6_host(monkeypatch):
    request=Request({'type':'http','scheme':'http','server':('::1',8765),'path':'/','headers':[(b'host',b'[::1]:8765')]})
    monkeypatch.delenv('ORH_VSCODE_SSH_AUTHORITY',raising=False)
    monkeypatch.setenv('ORH_SSH_USER','fixture')
    assert folder_url(request,'/home/fixture').startswith('vscode://vscode-remote/ssh-remote+fixture@%3A%3A1/')
