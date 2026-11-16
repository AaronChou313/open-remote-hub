"""Desktop update UI backed by the existing release and installer launcher."""
from pathlib import Path
import os
import platform
import subprocess
import sys
import tempfile
import threading
import urllib.request
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from app.remote_connect.api import administrator

router = APIRouter(prefix='/api/client/software', dependencies=[Depends(administrator)])
lock = threading.RLock()
state = {'phase':'idle','progress':0,'error':'','release':None}


def status():
    from app import launcher
    with lock:
        return dict(state,version=launcher.version(),platform=platform.system(),architecture=platform.machine(),
                    install_supported=bool(getattr(sys,'frozen',False)),project_url='https://github.com/AaronChou313/open-remote-hub')


@router.get('')
def info():
    return status()


def check_release():
    from app import launcher
    try:
        release = launcher.release_info()
        with lock:
            state.update(phase='available' if launcher.newer(release['version'],launcher.version()) else 'current',release=release,error='',progress=0)
    except Exception as error:
        with lock:state.update(phase='error',error='检查更新失败，请稍后重试。'+str(error))


@router.post('/check')
def check():
    with lock:
        if state['phase'] in ('checking','downloading','installing'):return status()
        state.update(phase='checking',error='')
        threading.Thread(target=check_release,daemon=True).start()
    return status()


def download_release(release):
    target=Path(tempfile.gettempdir())/'orh-updates'/release['name']
    part=target.with_suffix(target.suffix+'.part')
    try:
        target.parent.mkdir(parents=True,exist_ok=True)
        request=urllib.request.Request(release['url'],headers={'User-Agent':'OpenRemoteHub'})
        with urllib.request.urlopen(request,timeout=30) as response,part.open('wb') as output:
            total=int(response.headers.get('Content-Length') or release.get('size') or 0)
            received=0
            while block:=response.read(256*1024):
                output.write(block);received+=len(block)
                with lock:state['progress']=min(100,round(received/total*100)) if total else 0
            if total and received!=total:raise OSError('安装包下载中断')
        part.replace(target)
        with lock:state.update(phase='ready',progress=100,path=str(target))
    except Exception as error:
        part.unlink(missing_ok=True)
        with lock:state.update(phase='error',error='下载更新失败，请重试。'+str(error))


@router.post('/download')
def download():
    from app import launcher
    with lock:
        if state['phase']=='downloading':return status()
        release=state['release']
        if not release or not launcher.newer(release['version'],launcher.version()):raise HTTPException(409,'请先检查新版本')
        state.update(phase='downloading',progress=0,error='')
        threading.Thread(target=download_release,args=(dict(release),),daemon=True).start()
    return status()


def launch_installer(path):
    from app import launcher
    try:
        subprocess.Popen(launcher.command('--install-update',path),creationflags=launcher.CREATE_NO_WINDOW,close_fds=True,start_new_session=sys.platform!='win32')
    except OSError as error:
        with lock:state.update(phase='error',error='启动安装程序失败。'+str(error))


@router.post('/install')
def install(background: BackgroundTasks):
    if not getattr(sys,'frozen',False):raise HTTPException(409,'源码运行可从发行页面下载安装包')
    with lock:
        if state['phase']!='ready':raise HTTPException(409,'请先完成更新下载')
        state['phase']='installing'
        background.add_task(launch_installer,state['path'])
    return status()


def restart_application():
    from app import launcher
    subprocess.Popen(launcher.command('--restart-app'),creationflags=launcher.CREATE_NO_WINDOW,close_fds=True,start_new_session=sys.platform!='win32')


@router.post('/restart')
def restart(background: BackgroundTasks):
    if not getattr(sys,'frozen',False):raise HTTPException(409,'请通过源码启动方式重启')
    background.add_task(restart_application)
    return dict(phase='installing')
