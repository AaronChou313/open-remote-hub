"""Authenticated, read-only access to the current native Zellij pane buffer."""
import re
from fastapi import APIRouter,Depends,HTTPException
from app.access import admin
from app.zellij_manage import panes

router=APIRouter()

@router.get('/api/zellij/{name}/panes',dependencies=[Depends(admin)])
def list_panes(name:str):return panes(name)

@router.get('/api/zellij/{name}/output',dependencies=[Depends(admin)])
def pane_output(name:str,pane:str=''):
    from app import main
    terminals=[p for p in panes(name) if not p.get('is_plugin')]
    if not terminals:raise HTTPException(404,'没有终端窗格')
    if not pane:
        focused=next((p for p in terminals if p.get('is_focused')),terminals[0])
        pane='terminal_'+str(focused['id'])
    if not re.fullmatch(r'terminal_\d{1,6}',pane) or not any(pane=='terminal_'+str(p['id']) for p in terminals):raise HTTPException(400,'Pane ID 无效')
    output=main.cli(['zellij','--session',name,'action','dump-screen','--pane-id',pane,'--full'],3)[-65536:]
    return {'session':name,'pane':pane,'output':output}
