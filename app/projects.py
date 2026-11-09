"""Project registry and read-only repository insights; project files remain untouched."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app import file_access as fs, workspace_store as store
from app.workspace_commands import run

router=APIRouter(prefix='/api/projects',tags=['projects'])
lock=threading.RLock()
GIT=['git','--no-pager','-c','core.fsmonitor=false','-c','core.hooksPath='+os.devnull,'-c','diff.external=','-c','core.pager=cat','-c','log.showSignature=false']


def absolute(project):return str(Path(fs.root(project['root'])['path'])/project['path'])


def read_json(root,path):
    try:
        with fs.opened(root,path) as fd:
            if os.fstat(fd).st_size>1024**2:return {}
            value=json.loads(os.read(fd,1024**2+1))
            return value if isinstance(value,dict) else {}
    except (HTTPException,OSError,UnicodeError,ValueError):return {}


def detect(project):
    with fs.directory(project['root'],project['path']) as fd:
        names=set(os.listdir(fd));stack=[]
        for marker,label in [('pyproject.toml','Python'),('requirements.txt','Python'),('package.json','Node.js'),('Cargo.toml','Rust'),('go.mod','Go'),('pom.xml','Java'),('Dockerfile','Docker'),('compose.yml','Docker Compose'),('docker-compose.yml','Docker Compose')]:
            if marker in names and label not in stack:stack.append(label)
        git_marker=next((x for x in ('.git',) if x in names),None)
        if git_marker and fs.entry(fd,git_marker)['kind']=='link':git_marker=None
        return dict(stack=stack,git=bool(git_marker),environment_markers=sorted(names.intersection({'.venv','venv','environment.yml','environment.yaml','.python-version','.nvmrc','package-lock.json','pnpm-lock.yaml','yarn.lock'})))


def project(key):
    value=store.get('project',key)
    with fs.directory(value['root'],value['path']):pass
    return value


class Add(BaseModel):
    root:str
    path:str=''
    name:str=Field(min_length=1,max_length=100)


@router.get('')
def list_projects(q:str=''):
    result=[]
    for value in store.rows('project'):
        if q.casefold() not in (value['name']+' '+value['path']).casefold():continue
        try:result.append(dict(value,**detect(value),available=True))
        except (HTTPException,OSError):result.append(dict(value,available=False,stack=[],git=False))
    return {'projects':result}


@router.post('')
def add(body:Add):
    fs.parts(body.path)
    with lock,fs.directory(body.root,body.path):
        if any(x['root']==body.root and x['path']==body.path for x in store.rows('project')):raise HTTPException(409,'此目录已添加为项目')
        result=store.save('project',dict(name=body.name,root=body.root,path=body.path,environment=None,session='',tasks={}))
    return result


def git(key,kind):
    p=project(key)
    if not detect(p)['git']:return {'output':'当前项目目录不是 Git 仓库根目录','truncated':False}
    with fs.directory(p['root'],p['path']) as fd:
        top=run(GIT+['rev-parse','--show-toplevel'],fd)['output'].strip()
        if Path(top).resolve()!=Path(absolute(p)).resolve():raise HTTPException(403,'Git 工作区指向其他目录，未读取')
        metadata=run(GIT+['rev-parse','--absolute-git-dir'],fd)['output'].strip()
        # Worktrees are supported only if their metadata stays inside an authorized root.
        target=Path(metadata)
        if not any(target==Path(r['path']) or Path(r['path']) in target.parents for r in fs.roots()):raise HTTPException(403,'Git 元数据位于未授权目录')
        if fs.protected([part for part in target.parts if part!='.git']):raise HTTPException(403,'Git 元数据路径受保护')
        metadata_fd=os.open('/',fs.DIR)
        try:
            for part in target.parts[1:]:
                child=os.open(part,fs.DIR,dir_fd=metadata_fd);os.close(metadata_fd);metadata_fd=child
        except OSError as e:raise fs.error(e)
        finally:os.close(metadata_fd)
        commands={'status':['status','--short','--branch','--untracked-files=normal'],'branches':['branch','--list'],'commits':['log','-10','--format=%h %ad %s','--date=short'],'diff':['diff','--no-ext-diff','--no-textconv','--stat','--patch','--'],'staged':['diff','--cached','--no-ext-diff','--no-textconv','--stat','--patch','--']}
        if kind not in commands:raise HTTPException(400,'不支持的 Git 查询')
        argv=commands[kind]
        if kind in ('diff','staged'):
            excluded=list(fs.BLOCKED|fs.SENSITIVE)+['.env*','*.pem','*.key','*.p12','*.pfx','.orh-*']
            argv=argv+['.']+[':(glob,icase,exclude)**/'+name for name in excluded]+[':(glob,icase,exclude)**/'+name+'/**' for name in fs.BLOCKED]
        return run(GIT+argv,fd)


def presets(p):
    package=read_json(p['root'],'/'.join(filter(None,[p['path'],'package.json'])))
    result=[]
    scripts=package.get('scripts',{})
    if isinstance(scripts,dict):
        for key in ('dev','start','build','test'):
            script=scripts.get(key)
            if not isinstance(script,str):continue
            lifecycle=[(n,scripts.get(n)) for n in ('pre'+key,key,'post'+key) if isinstance(scripts.get(n),str)]
            if sum(len(v) for n,v in lifecycle)>8192:continue
            bound=p.get('environment') or {}
            if bound.get('kind')=='node':argv=[str(Path(bound['path'])/'bin/node'),str(Path(bound['path'])/'bin/npm'),'run',key]
            elif bound.get('kind')=='conda' and shutil.which('conda'):argv=[shutil.which('conda'),'run','--prefix',bound['path'],'--no-capture-output','npm','run',key]
            else:argv=[shutil.which('npm') or 'npm','run',key]
            value=dict(key=key,label='npm run '+key,argv=argv,description='\n'.join(n+': '+v for n,v in lifecycle))
            value['digest']=hashlib.sha256(json.dumps([value,p.get('environment'),package],sort_keys=True).encode()).hexdigest();result.append(value)
    with fs.directory(p['root'],p['path']) as fd:names=set(os.listdir(fd))
    bound=p.get('environment') or {}
    python=str(Path(bound['path'])/'bin/python') if bound.get('kind') in ('venv','runtime','conda') else shutil.which('python3') or 'python3'
    for marker,key,args,label in [('tests','pytest',['-m','pytest'],'运行 pytest'),('manage.py','django',['manage.py','runserver'],'启动 Django 开发服务')]:
        if marker not in names:continue
        value=dict(key=key,label=label,argv=[python,*args],description='执行项目代码与配置：'+label)
        value['digest']=hashlib.sha256(json.dumps([value,p.get('environment')],sort_keys=True).encode()).hexdigest();result.append(value)
    return result


@router.get('/{key}')
def detail(key:str):
    p=project(key)
    return dict(p,**detect(p),absolute_path=absolute(p),presets=presets(p))


@router.get('/{key}/git')
def git_info(key:str,kind:str='status'):return git(key,kind)


class Update(BaseModel):
    revision:str
    action:str
    confirm:str=''
    environment:str=''
    session:str=''
    preset:str=''
    digest:str=''


def clean(p):return {k:v for k,v in p.items() if k not in ('id','revision')}


@router.post('/{key}')
def update(key:str,body:Update):
    with lock:
        p=store.get('project',key)
        if p['revision']!=body.revision:raise HTTPException(409,'项目记录已改变，请刷新')
        if body.action=='remove':
            if body.confirm!=key:raise HTTPException(400,'请确认移除项目记录；不会删除项目文件')
            store.remove('project',key,body.revision);return {'ok':True}
        p=project(key);value=clean(p)
        if body.action=='environment':
            if p.get('environment') and body.confirm!=key:raise HTTPException(400,'请确认更改环境绑定')
            if body.environment:
                from app.environments import environment
                env=environment(body.environment)
                value['environment']=dict(id=env['id'],name=env['name'],path=env['path'],kind=env['kind'])
            else:value['environment']=None
        elif body.action=='terminal':
            from app.terminal_entry import prepare
            # Only new sessions receive cwd. No commands are injected into existing panes.
            with fs.directory(p['root'],p['path']):result=prepare(body.session,cwd=absolute(p))
            value['session']=body.session
            saved=store.save('project',value,key,p['revision']);return dict(saved,terminal=result)
        elif body.action=='run':
            if body.confirm!=key:raise HTTPException(400,'需要确认实际任务命令')
            preset=next((x for x in presets(p) if x['key']==body.preset),None)
            if not preset or body.digest!=preset['digest']:raise HTTPException(409,'预设任务或环境已改变，请重新查看命令')
            from app import main
            task=value['tasks'].get(body.preset)
            expected_argv=preset['argv']
            if task:
                registered=main.read_tasks().get(task)
                if not registered or registered['argv']!=expected_argv or registered['cwd']!=absolute(p):task=None
            if not task:
                task=main.task_create(main.Task(name=p['name']+' · '+preset['label'],argv=expected_argv,cwd=absolute(p)))['id']
                value['tasks'][body.preset]=task
                store.save('project',value,key,p['revision'])
            main.task_action(task,main.Action(action='start',confirm=task))
            return {'task':task}
        else:raise HTTPException(400,'不支持的项目操作')
        return store.save('project',value,key,p['revision'])
