"""Scoped Zellij operations: session -> tab ID -> terminal pane ID."""
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time
import secrets
import psutil
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from app.access import admin
from app.zellij_sessions import host_sessions

router=APIRouter()
mutex=threading.RLock()


def main():
    from app import main as m
    return m


def current(name):
    return next((s for s in host_sessions() if s['name']==name),None)


def backup(name):
    m=main()
    from app.zellij_sessions import cache_roots
    saved=[]
    for root in cache_roots():
        for folder in root.glob('*/session_info/'+name):
            if not folder.is_dir() or folder.is_symlink():continue
            if not saved:
                destination=m.DATA/'backups'/('session-'+time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3))
                destination.mkdir(mode=0o700,parents=True)
            target=destination/folder.parent.parent.name/name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copytree(folder,target)
            saved.append(target)
    return str(destination.relative_to(m.DATA)) if saved else None


def reap_orphan(name):
    row=current(name)
    if not row or not row.get('orphan'):return
    try:
        p=psutil.Process(row['pid']);args=p.cmdline()
        socket=Path(args[args.index('--server')+1])
        def safe():
            return p.is_running() and p.create_time()==row['created'] and socket.name==name and not socket.exists() and not p.children(recursive=True)
        if not safe():raise HTTPException(409,'会话状态改变，未清理残留进程')
        p.terminate()
        try:p.wait(2)
        except psutil.TimeoutExpired:
            if not safe():raise HTTPException(409,'进程仍有任务，未强制结束')
            p.kill();p.wait(2)
    except psutil.NoSuchProcess:pass


def stop(name):
    m=main();row=current(name)
    if not row or row['status']!='running':return
    m.cli(['zellij','--session',name,'action','save-session'],4)
    m.cli(['zellij','kill-session',name],4)
    for attempt in range(25):
        row=current(name)
        if not row or row['status']!='running':return
        if attempt==8:m.cli(['zellij','kill-session',name],4)
        time.sleep(.1)
    raise HTTPException(409,'会话尚未结束，未强制终止；请检查终端后重试')


def mutate(name,action,new_name=''):
    m=main();m.zname(name)
    with mutex:
        if action=='create':return {'output':m.cli(['zellij','--config',str(m.ROOT/'config/zellij.kdl'),'attach','--create-background',name],8)}
        if action=='rename':
            m.zname(new_name)
            if new_name==name:return {'output':''}
            if current(new_name):raise HTTPException(409,'该会话名称已存在')
            m.cli(['zellij','--session',name,'action','save-session'],4)
            return {'output':m.cli(['zellij','--session',name,'action','rename-session',new_name],4)}
        if action=='kill':stop(name);return {'output':'会话已结束'}
        if action not in ('delete','purge'):raise HTTPException(400,'Unsupported action')
        row=current(name)
        if row and row['status']=='running':
            if action!='purge':raise HTTPException(409,'会话仍在运行，请选择“结束并删除”')
            stop(name)
        saved=backup(name)
        reap_orphan(name)
        # A stale browser row may be deleted by another tab: deletion is idempotent.
        if not current(name):return {'output':'会话已删除','already_deleted':True,'backup':saved}
        output=m.cli(['zellij','delete-session',name],5)
        for _ in range(10):
            if not current(name):return {'output':output,'backup':saved}
            time.sleep(.1)
        raise HTTPException(409,'Zellij 尚未移除会话记录，请稍后重试；备份已保留')


def panes(name):
    m=main();m.zname(name)
    row=current(name)
    if not row or row['status']!='running':raise HTTPException(409,'会话已退出')
    return json.loads(m.cli(['zellij','--session',name,'action','list-panes','--all','--json'],3))


def tab_rows(name):
    m=main();m.zname(name)
    row=current(name)
    if not row or row['status']!='running':raise HTTPException(409,'会话已退出')
    return json.loads(m.cli(['zellij','--session',name,'action','list-tabs','--all','--json'],3))


@router.get('/api/zellij/{name}/structure',dependencies=[Depends(admin)])
def structure(name:str):
    m=main();m.zname(name);row=current(name)
    if not row:raise HTTPException(404,'会话已删除')
    if row['status']!='running':return {'name':name,'status':'exited','tabs':[]}
    rows=panes(name);tabs={t['tab_id']:dict(id=t['tab_id'],position=t['position'],name=t['name'],panes=[],plugins=[],pending=t.get('viewport_rows',0)==0) for t in tab_rows(name)}
    for p in rows:
        key=p['tab_id']
        tab=tabs.setdefault(key,dict(id=key,position=p.get('tab_position',0),name=p.get('tab_name') or '未命名标签页',panes=[],plugins=[]))
        if p.get('is_plugin'):
            tab['plugins'].append({'id':'plugin_'+str(p['id']),'title':p.get('title'),'plugin':p.get('plugin_url')})
        else:
            tab['panes'].append(dict(id='terminal_'+str(p['id']),title=p.get('title') or '终端',command=p.get('pane_command') or p.get('terminal_command') or '',cwd=p.get('pane_cwd') or '',focused=p.get('is_focused',False),floating=p.get('is_floating',False),held=p.get('is_held',False),exited=p.get('exited',False)))
    return {'name':name,'status':'running','pid':row['pid'],'tabs':sorted(tabs.values(),key=lambda x:x['position'])}


def settle(name,predicate,tabs=False):
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        try:rows=tab_rows(name) if tabs else panes(name)
        except HTTPException as e:
            if e.status_code==409:rows=[]
            else:raise
        if predicate(rows):return True
        time.sleep(.08)
    return False


class Change(BaseModel):
    action:str
    confirm:str=''
    name:str=Field(default='',max_length=80)


def check(body,name):
    if body.confirm!=name:raise HTTPException(400,'确认目标不匹配')
    if '\x00' in body.name or '\n' in body.name:raise HTTPException(400,'名称无效')


@router.post('/api/zellij/{name}/tabs',dependencies=[Depends(admin)])
def new_tab(name:str,body:Change):
    m=main();m.zname(name);check(body,name);panes(name)
    if body.action!='create':raise HTTPException(400,'Unsupported action')
    args=['zellij','--session',name,'action','new-tab','--no-focus']
    if body.name:args+=['--name='+body.name]
    result=m.cli(args,5)
    identifier=int(result.strip()) if result.strip().isdigit() else None
    settled=settle(name,lambda rows:any(p.get('tab_id')==identifier if identifier is not None else p.get('name')==body.name for p in rows),tabs=True)
    m.audit('zellij-tab',name,'create');return {'output':result,'pending':not settled}


@router.post('/api/zellij/{name}/tabs/{tab_id}',dependencies=[Depends(admin)])
def tab_action(name:str,tab_id:int,body:Change):
    m=main();check(body,name)
    before=panes(name)
    if not any(p.get('tab_id')==tab_id for p in tab_rows(name)):raise HTTPException(404,'标签页已关闭')
    if body.action=='close':args=['close-tab','--tab-id',str(tab_id)]
    elif body.action=='rename' and body.name:args=['rename-tab','--tab-id',str(tab_id),'--',body.name]
    elif body.action=='pane':args=['new-pane','--tab-id',str(tab_id),'--no-focus']
    else:raise HTTPException(400,'Unsupported action')
    result=m.cli(['zellij','--session',name,'action',*args],5)
    old_ids={p['id'] for p in before if not p.get('is_plugin')}
    if body.action=='close':check_result=lambda rows:not any(p.get('tab_id')==tab_id for p in rows)
    elif body.action=='rename':check_result=lambda rows:any(p.get('tab_id')==tab_id and p.get('name')==body.name for p in rows)
    else:check_result=lambda rows:any(p.get('tab_id')==tab_id and not p.get('is_plugin') and p['id'] not in old_ids for p in rows)
    settled=settle(name,check_result,tabs=body.action in ('close','rename'))
    m.audit('zellij-tab',name+'/'+str(tab_id),body.action);return {'output':result,'pending':not settled}


@router.post('/api/zellij/{name}/panes/{pane_id}',dependencies=[Depends(admin)])
def pane_action(name:str,pane_id:str,body:Change):
    m=main();check(body,name)
    if not re.fullmatch(r'terminal_\d{1,6}',pane_id):raise HTTPException(400,'Pane ID 无效')
    if not any(not p.get('is_plugin') and pane_id=='terminal_'+str(p['id']) for p in panes(name)):raise HTTPException(404,'终端窗格已关闭')
    if body.action!='close':raise HTTPException(400,'Unsupported action')
    result=m.cli(['zellij','--session',name,'action','close-pane','--pane-id',pane_id],5)
    settled=settle(name,lambda rows:not any(not p.get('is_plugin') and pane_id=='terminal_'+str(p['id']) for p in rows))
    m.audit('zellij-pane',name+'/'+pane_id,'close');return {'output':result,'pending':not settled}
