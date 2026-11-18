"""Session lifecycle only; native Zellij owns tabs and panes."""
import os
import json
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
        socket=Path(args[args.index('--server')+1]).with_name(name)
        def safe():
            return p.is_running() and p.create_time()==row['created'] and socket.name==name and not socket.exists() and not p.children(recursive=True)
        if not safe():raise HTTPException(409,'会话状态改变，未清理残留进程')
        p.terminate()
        try:p.wait(2)
        except psutil.TimeoutExpired:
            if not safe():raise HTTPException(409,'进程仍有任务，未强制结束')
            p.kill();p.wait(2)
    except psutil.NoSuchProcess:pass


def stop(name,save=True):
    m=main();row=current(name)
    if not row or row['status']!='running':return
    try:
        process=psutil.Process(row['pid'])
        if process.create_time()!=row['created']:
            raise HTTPException(409,'会话进程已变化，请刷新后重试')
        members=[process,*process.children(recursive=True)]
    except psutil.NoSuchProcess:return
    if save:
        try:m.cli(['zellij','--session',name,'action','save-session'],2)
        except HTTPException as error:
            if error.status_code!=503:raise
    try:m.cli(['zellij','kill-session',name],2)
    except HTTPException as error:
        if error.status_code!=503:raise
    _,alive=psutil.wait_procs(members,timeout=.5)
    for member in alive:
        try:member.terminate()
        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
    _,alive=psutil.wait_procs(alive,timeout=2)
    for member in alive:
        try:member.kill()
        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
    _,alive=psutil.wait_procs(alive,timeout=2)
    if alive:raise HTTPException(409,'会话任务仍在退出，请稍后重试')


def delete_history(name):
    from app.zellij_sessions import cache_roots
    for root in cache_roots():
        for folder in root.glob('*/session_info/'+name):
            try:
                if folder.is_symlink():folder.unlink()
                elif folder.is_dir():shutil.rmtree(folder)
            except FileNotFoundError:pass


def rename(name,new_name):
    m=main()
    row=current(name)
    if not row or row['status']!='running':raise HTTPException(409,'请先恢复会话，再重命名')
    if current(new_name):raise HTTPException(409,'该会话名称已存在')
    process=psutil.Process(row['pid'])
    args=process.cmdline()
    contract=Path(args[args.index('--server')+1]).parent.name
    m.cli(['zellij','--session',name,'action','save-session'],4)
    output=m.cli(['zellij','--session',name,'action','rename-session',new_name],4)
    from app.zellij_sessions import cache_roots
    # Zellij renames the socket and cache folder, while --server in argv keeps
    # its original name. Bind the renamed folder to that same live process.
    for root in cache_roots():
        folder=root/contract/'session_info'/new_name
        if not folder.is_dir():continue
        marker=folder/'orh-process.json'
        temporary=folder/'orh-process.json.tmp'
        temporary.write_text(json.dumps({'pid':row['pid'],'created':row['created']}))
        temporary.replace(marker)
        old=root/folder.parent.parent.name/'session_info'/name/'orh-process.json'
        old.unlink(missing_ok=True)
    renamed=current(new_name)
    if not renamed or renamed['status']!='running':
        raise HTTPException(409,'会话重命名状态仍在同步，请刷新后重试')
    return {'output':output}


def mutate(name,action,new_name=''):
    m=main();m.zname(name)
    from app.terminal_entry import session_lock
    with mutex,session_lock(name):
        if action=='create':return {'output':m.cli(['zellij','--config',str(m.ROOT/'config/zellij.kdl'),'attach','--create-background',name],8,**({'cwd':str(Path.home())} if not current(name) else {}))}
        if action=='rename':
            m.zname(new_name)
            if new_name==name:return {'output':''}
            with session_lock(new_name):return rename(name,new_name)
        if action=='kill':stop(name);return {'output':'会话已结束'}
        if action not in ('delete','purge'):raise HTTPException(400,'Unsupported action')
        row=current(name)
        saved=backup(name) if action=='purge' else None
        if row and row['status']=='running':
            if action!='purge':raise HTTPException(409,'会话仍在运行，请选择“结束并删除”')
            stop(name,save=False)
        if saved is None:saved=backup(name)
        reap_orphan(name)
        # A stale browser row may be deleted by another tab: deletion is idempotent.
        if not current(name):return {'output':'会话已删除','already_deleted':True,'backup':saved}
        delete_history(name)
        for _ in range(10):
            if not current(name):return {'output':'会话已删除','backup':saved}
            time.sleep(.1)
        raise HTTPException(409,'Zellij 尚未移除会话记录，请稍后重试；备份已保留')
