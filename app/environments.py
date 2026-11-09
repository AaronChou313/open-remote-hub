"""Installed tool inventory, passive environment metadata and explicit venv creation."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import threading
import time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app import file_access as fs, workspace_store as store
from app.workspace_commands import run

router=APIRouter(prefix='/api/environments',tags=['environments'])
mutex=threading.RLock();cached=None;cached_at=0


def identifier(kind,path):return hashlib.sha256((kind+':'+path).encode()).hexdigest()[:20]


def installed_tools():
    global cached,cached_at
    with mutex:
        if cached is not None and time.monotonic()-cached_at<30:return cached
        def probe(name):
            executable=shutil.which(name)
            if not executable:return dict(name=name,available=False,path=None,version=None)
            try:value=run([executable,'--version'],timeout=4,limit=4096)['output'].strip().splitlines()[0]
            except (HTTPException,IndexError):value='版本查询不可用'
            return dict(name=name,available=True,path=executable,version=value)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            cached=list(pool.map(probe,['python3','conda','node','npm','git','zellij','docker','brew']))
        cached_at=time.monotonic();return cached


def location(path):
    p=Path(path)
    for root in sorted(fs.roots(),key=lambda x:len(x['path']),reverse=True):
        base=Path(root['path'])
        if p==base or base in p.parents:
            rel=str(p.relative_to(base));return root['id'],'' if rel=='.' else rel
    raise HTTPException(403,'环境路径不在授权目录内')


def value(kind,path,name,**extra):return dict(id=identifier(kind,path),kind=kind,path=path,name=name,**extra)


def discover():
    environments=[value('runtime',sys.prefix,'RemoteHub Python（只读）',version=sys.version.split()[0])]
    for p in store.rows('project'):
        for suffix in ('.venv','venv'):
            path='/'.join(filter(None,[p['path'],suffix]))
            try:
                with fs.directory(p['root'],path) as fd:
                    child=os.open('pyvenv.cfg',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
                    try:fs.regular(child);cfg=os.read(child,65536).decode(errors='replace')
                    finally:os.close(child)
                version=next((line.split('=',1)[1].strip() for line in cfg.splitlines() if line.startswith('version') and '=' in line),'未知')
                environments.append(value('venv',str(Path(fs.root(p['root'])['path'])/path),p['name']+' / '+suffix,version=version,project=p['id']))
            except (HTTPException,OSError):continue
    node=shutil.which('node')
    if node:
        prefix=str(Path(node).resolve().parent.parent)
        environments.append(value('node',prefix,'Node.js / 主机安装',version=next((t['version'] for t in installed_tools() if t['name']=='node'),'未知')))
    conda=shutil.which('conda')
    if conda:
        try:
            data=json.loads(run([conda,'env','list','--json'],timeout=8)['output'])
            for path in data.get('envs',[])[:100]:
                if isinstance(path,str) and Path(path).is_absolute():environments.append(value('conda',path,'Conda / '+Path(path).name,version='见依赖列表'))
        except (HTTPException,ValueError):pass
    seen=set();return [e for e in environments if not (e['id'] in seen or seen.add(e['id']))]


def environment(key):return next((e for e in discover() if e['id']==key),None) or unavailable()


def unavailable():raise HTTPException(404,'环境已不存在或暂不可检测，请刷新')


@router.get('')
def listing():return {'tools':installed_tools(),'environments':discover(),'python':sys.version.split()[0]}


@router.get('/software')
def software():
    from app.platforms import software_inventory
    return software_inventory()


def dependencies(env):
    key,rel=location(env['path']);result=[];truncated=False
    if env['kind']=='node':
        npm=shutil.which('npm')
        if not npm:return dict(packages=[],truncated=False)
        data=json.loads(run([npm,'list','--global','--depth=0','--json'],timeout=10)['output'])
        return dict(packages=[{'name':str(k)[:200],'version':str(v.get('version',''))[:200]} for k,v in list(data.get('dependencies',{}).items())[:3000]],truncated=False)
    with fs.directory(key,rel) as fd:
        # Read metadata without executing a project's interpreter, pip, .pth or hooks.
        if env['kind']=='conda':
            meta=os.open('conda-meta',fs.DIR,dir_fd=fd)
            try:
                for name in os.listdir(meta)[:3000]:
                    if not name.endswith('.json'):continue
                    child=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=meta)
                    try:
                        fs.regular(child);raw=os.read(child,65537)
                        if len(raw)>65536:continue
                        item=json.loads(raw);result.append({'name':str(item.get('name',''))[:200],'version':str(item.get('version',''))[:200]})
                    except (ValueError,OSError):continue
                    finally:os.close(child)
            finally:os.close(meta)
        else:
            lib=os.open('lib',fs.DIR,dir_fd=fd)
            try:
                for name in os.listdir(lib)[:100]:
                    if not re.fullmatch(r'python\d+\.\d+',name):continue
                    sub=os.open(name,fs.DIR,dir_fd=lib)
                    try:
                        try:site=os.open('site-packages',fs.DIR,dir_fd=sub)
                        except FileNotFoundError:continue
                        try:
                            names=os.listdir(site);truncated|=len(names)>5000
                            for entry in names[:5000]:
                                if not entry.endswith('.dist-info'):continue
                                package=os.open(entry,fs.DIR,dir_fd=site)
                                try:
                                    metadata=os.open('METADATA',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=package)
                                    try:fs.regular(metadata);raw=os.read(metadata,65536).decode(errors='replace')
                                    finally:os.close(metadata)
                                    fields={}
                                    for line in raw.splitlines():
                                        if not line:break
                                        if line.startswith(('Name: ','Version: ')):
                                            k,v=line.split(': ',1);fields[k]=v[:200]
                                    if fields.get('Name'):result.append({'name':fields['Name'],'version':fields.get('Version','')})
                                except (OSError,HTTPException):continue
                                finally:os.close(package)
                        finally:os.close(site)
                    finally:os.close(sub)
            finally:os.close(lib)
    return dict(packages=sorted(result,key=lambda x:x['name'].casefold()),truncated=truncated)


@router.get('/{key}')
def detail(key:str):
    env=environment(key)
    try:return dict(env,**dependencies(env))
    except OSError as e:raise fs.error(e)


class Create(BaseModel):
    project:str
    name:str='.venv'
    confirm:str=''
    digest:str=''


def plan(body):
    from app.projects import project,absolute
    p=project(body.project)
    if body.name not in ('.venv','venv'):raise HTTPException(400,'本版本仅创建 .venv 或 venv 目录')
    path='/'.join(filter(None,[p['path'],body.name]));fs.parts(path,False)
    with fs.parent(p['root'],path,write=True) as (fd,name):
        try:os.stat(name,dir_fd=fd,follow_symlinks=False)
        except FileNotFoundError:pass
        else:raise HTTPException(409,'环境目录已存在，不允许覆盖或复用')
    value=dict(project=p['id'],revision=p['revision'],root=p['root'],path=path,absolute_path=str(Path(absolute(p))/body.name),argv=[sys.executable,'-I','-m','venv',body.name],effect='创建全新 Python venv，包含本机 bundled pip；不联网安装包，不覆盖目录，不自动绑定')
    value['digest']=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
    return value


@router.post('/plan')
def create_plan(body:Create):return plan(body)


@router.post('/create')
def create(body:Create):
    with mutex,fs.mutex:
        value=plan(body)
        if body.confirm!=body.project or body.digest!=value['digest']:raise HTTPException(400,'请先查看并确认环境创建计划')
        with fs.parent(value['root'],value['path'],write=True) as (fd,name):
            os.mkdir(name,0o700,dir_fd=fd)
            child=os.open(name,fs.DIR,dir_fd=fd)
            try:
                result=run([sys.executable,'-I','-m','venv','.'],cwd_fd=child,timeout=45,limit=65536)
            except HTTPException as e:raise HTTPException(e.status_code,'环境创建未完成，目录已保留供检查；未覆盖其他内容、未绑定。'+str(e.detail))
            finally:os.close(child)
        from app.main import audit
        audit('environment',value['absolute_path'],'create-venv')
        return dict(ok=True,path=value['absolute_path'],output=result['output'])
