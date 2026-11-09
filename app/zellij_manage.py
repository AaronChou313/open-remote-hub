"""Session lifecycle only; native Zellij owns tabs and panes."""
import os
from pathlib import Path
import shutil
import threading
import time
import secrets
import psutil
from fastapi import HTTPException
from app.zellij_sessions import host_sessions

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
