"""Bounded file operations; streams keep an already validated descriptor open."""
import asyncio
import contextlib
import json
import os
from pathlib import Path
import secrets
import stat
import time
from urllib.parse import quote
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from app import file_access as fs

router=APIRouter(prefix='/api/files',tags=['files'])
TEXT_LIMIT=1024**2


def audit(root,path,action):
    from app.main import audit as record
    record('file',root+'/'+path,action)


@router.get('/roots')
def roots():return {'roots':fs.roots()}


@router.get('/list')
def listing(root:str,path:str='',offset:int=0):
    if offset<0:raise HTTPException(400,'无效分页')
    base=Path(fs.root(root)['path'])/path
    with fs.directory(root,path) as fd:
        items=[];truncated=False
        with os.scandir(fd) as iterator:
            for row in iterator:
                if row.name.startswith('.orh-') or row.name=='.remotehub-trash':continue
                try:
                    item=fs.entry(fd,row.name);item['read_only']=fs.readonly(base/row.name);item['protected']|=fs.sensitive_absolute(base/row.name);items.append(item)
                except FileNotFoundError:continue
                if len(items)>=10000:truncated=True;break
        items.sort(key=lambda x:(x['kind']!='directory',x['name'].casefold()))
        absolute=Path(fs.root(root)['path'])/path
        return dict(root=root,path=path,entries=items[offset:offset+200],next_offset=offset+200 if len(items)>offset+200 else None,truncated=truncated,read_only=fs.readonly(absolute))


@router.get('/search')
def search(root:str,path:str='',q:str=''):
    if not q.strip() or len(q)>100:raise HTTPException(400,'搜索词长度须为 1–100')
    found=[];count=0;start=time.monotonic();truncated=False;base=Path(fs.root(root)['path'])
    def walk(folder,depth=0):
        nonlocal count,truncated
        if depth>64:truncated=True;return
        with fs.directory(root,folder) as fd:
            with os.scandir(fd) as iterator:
                for row in iterator:
                    count+=1
                    if count>10000 or len(found)>=100 or time.monotonic()-start>3:truncated=True;return
                    try:item=fs.entry(fd,row.name)
                    except FileNotFoundError:continue
                    if item['protected'] or fs.sensitive_absolute(base/folder/row.name):continue
                    rel='/'.join(filter(None,[folder,row.name]))
                    if q.casefold() in row.name.casefold():found.append(dict(item,path=rel))
                    if item['kind']=='directory':
                        try:walk(rel,depth+1)
                        except HTTPException:continue
                    if truncated:return
    walk(path)
    return dict(entries=found,truncated=truncated)


@router.get('/text')
def text(root:str,path:str):
    with fs.opened(root,path) as fd:
        before=fs.regular(fd)
        if before.st_size>TEXT_LIMIT:raise HTTPException(413,'文本编辑/预览上限为 1 MiB，请下载文件')
        raw=os.read(fd,TEXT_LIMIT+1)
        if len(raw)>TEXT_LIMIT:raise HTTPException(413,'文件过大')
        try:
            value=raw.decode('utf-8')
            if '\x00' in value:raise ValueError()
        except (UnicodeError,ValueError):raise HTTPException(415,'不是 UTF-8 文本，请下载或使用图片预览')
        if fs.version(before)!=fs.version(os.fstat(fd)):raise HTTPException(409,'文件正在变更，请重试')
        return dict(text=value,revision=fs.version(before),path=path)


@router.get('/download')
def download(request:Request,root:str,path:str):
    # Duplicate the verified descriptor: StreamingResponse never reopens a path.
    with fs.opened(root,path) as source:fd=os.dup(source);size=os.fstat(source).st_size
    start=0;end=size-1;status=200
    try:
        header=request.headers.get('range')
        if header:
            import re
            match=re.fullmatch(r'bytes=(\d*)-(\d*)',header)
            if not match or not any(match.groups()):raise ValueError()
            a,b=match.groups()
            start=int(a) if a else max(0,size-int(b));end=min(int(b),size-1) if a and b else size-1
            if start>end or start>=size:raise ValueError()
            status=206
        os.lseek(fd,start,os.SEEK_SET)
    except ValueError:
        os.close(fd);raise HTTPException(416,'无效范围',headers={'Content-Range':f'bytes */{size}'})
    async def chunks():
        left=max(0,end-start+1)
        try:
            while left:
                data=await asyncio.to_thread(os.read,fd,min(256*1024,left))
                if not data:break
                left-=len(data);yield data
        finally:os.close(fd)
    ext=Path(path).suffix.lower()
    mime={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.gif':'image/gif','.webp':'image/webp'}.get(ext,'application/octet-stream')
    headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(Path(path).name,safe=''),'Accept-Ranges':'bytes','Content-Length':str(max(0,end-start+1))}
    if status==206:headers['Content-Range']=f'bytes {start}-{end}/{size}'
    return StreamingResponse(chunks(),status_code=status,media_type=mime,headers=headers)


class Edit(BaseModel):
    root:str
    path:str
    text:str=Field(max_length=TEXT_LIMIT)
    revision:str
    confirm:str


@router.post('/text')
def edit(body:Edit):
    if body.confirm!=body.path:raise HTTPException(400,'需要确认覆盖目标')
    data=body.text.encode('utf-8')
    if len(data)>TEXT_LIMIT:raise HTTPException(413,'文本上限为 1 MiB')
    with fs.mutex,fs.parent(body.root,body.path,write=True) as (fd,name):
        fs.check(fd,name,body.revision)
        with fs.opened(body.root,body.path) as existing:mode=stat.S_IMODE(os.fstat(existing).st_mode)&0o777
        temp='.orh-'+secrets.token_hex(16)
        child=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
        try:
            with os.fdopen(child,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno());os.fchmod(f.fileno(),mode)
            fs.check(fd,name,body.revision)
            os.replace(temp,name,src_dir_fd=fd,dst_dir_fd=fd)
            result=fs.entry(fd,name)
        finally:
            with contextlib.suppress(FileNotFoundError):os.unlink(temp,dir_fd=fd)
    audit(body.root,body.path,'edit');return result


@router.post('/upload')
async def upload(request:Request,root:str,path:str):
    limit=max(1,min(8192,int(os.environ.get('ORH_MAX_UPLOAD_MB','2048'))))*1024**2
    length=request.headers.get('content-length')
    if length and (not length.isdecimal() or int(length)>limit):raise HTTPException(413,'上传超过配置上限')
    with fs.parent(root,path,write=True) as (fd,name):
        temp='.orh-'+secrets.token_hex(16);total=0
        child=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
        try:
            with os.fdopen(child,'wb') as f:
                async for data in request.stream():
                    total+=len(data)
                    if total>limit:raise HTTPException(413,'上传超过配置上限')
                    await asyncio.to_thread(f.write,data)
                await asyncio.to_thread(f.flush);await asyncio.to_thread(os.fsync,f.fileno())
            # Publication itself is atomic no-replace; do not wait for a worker's
            # long filesystem lock on the event loop.
            fs.rename_exclusive(fd,temp,fd,name)
            result=fs.entry(fd,name)
        finally:
            with contextlib.suppress(FileNotFoundError):os.unlink(temp,dir_fd=fd)
    audit(root,path,'upload');return result


class Operation(BaseModel):
    root:str
    path:str
    action:str
    revision:str=''
    destination:str=''
    destination_root:str=''
    confirm:str=''


def copy_file(srcfd,src,dstfd,dst):
    before=fs.entry(srcfd,src)
    a=os.open(src,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=srcfd)
    try:
        original=fs.regular(a)
        if original.st_size>1024**3:raise HTTPException(413,'复制文件上限为 1 GiB')
        b=os.open(dst,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=dstfd)
        with os.fdopen(b,'wb') as target:
            copied=0
            while True:
                data=os.read(a,256*1024)
                if not data:break
                copied+=len(data)
                if copied>1024**3:raise HTTPException(413,'复制文件超过 1 GiB')
                target.write(data)
            target.flush();os.fsync(target.fileno())
        if fs.version(original)!=fs.version(os.fstat(a)) or fs.version(original)!=before['revision']:raise HTTPException(409,'复制过程中源文件发生变化')
    finally:os.close(a)


def clean_staging(fd,name):
    # Only our exclusive staging object; never a client-chosen recursive target.
    s=os.stat(name,dir_fd=fd,follow_symlinks=False)
    if stat.S_ISDIR(s.st_mode):
        child=os.open(name,fs.DIR,dir_fd=fd)
        try:
            for sub in os.listdir(child):clean_staging(child,sub)
        finally:os.close(child)
        os.rmdir(name,dir_fd=fd)
    else:os.unlink(name,dir_fd=fd)


@router.post('/operation')
def operate(body:Operation):
    if body.action not in ('mkdir','copy','move','rename','delete'):raise HTTPException(400,'不支持的文件操作')
    if body.action in ('delete','move','rename') and body.confirm!=body.path:raise HTTPException(400,'需要确认源路径和影响')
    with fs.mutex,fs.parent(body.root,body.path,write=body.action!='copy') as (srcfd,src):
        if body.action=='mkdir':
            os.mkdir(src,mode=0o700,dir_fd=srcfd);audit(body.root,body.path,'mkdir');return {'ok':True}
        item=fs.check(srcfd,src,body.revision)
        if item['kind']=='directory':
            child=os.open(src,fs.DIR,dir_fd=srcfd)
            try:tree=list(fs.scan_tree(child,base=Path(fs.root(body.root)['path'])/body.path))
            finally:os.close(child)
        if body.action=='delete':
            with contextlib.nullcontext(srcfd) as rootfd:
                try:os.mkdir('.remotehub-trash',0o700,dir_fd=rootfd)
                except FileExistsError:pass
                trash=os.open('.remotehub-trash',fs.DIR,dir_fd=rootfd)
                try:
                    name=secrets.token_hex(16)+'-'+src
                    fs.check(srcfd,src,body.revision)
                    fs.rename_exclusive(srcfd,src,trash,name)
                finally:os.close(trash)
            audit(body.root,body.path,'trash');return {'ok':True,'trash':name}
        destination_root=body.destination_root or body.root
        if body.action in ('move','rename') and destination_root!=body.root:raise HTTPException(400,'跨授权根目录请先复制，核验后删除')
        fs.parts(body.destination,False)
        if destination_root==body.root and (body.destination==body.path or body.destination.startswith(body.path+'/')):raise HTTPException(400,'目标不能是自身或其子目录')
        with fs.parent(destination_root,body.destination,write=True) as (dstfd,dst):
            if body.action in ('move','rename'):
                fs.check(srcfd,src,body.revision);fs.rename_exclusive(srcfd,src,dstfd,dst)
            else:
                temp='.orh-'+secrets.token_hex(16)
                try:
                    if item['kind']=='directory':
                        os.mkdir(temp,0o700,dir_fd=dstfd)
                        # Copy using pinned source/target descriptors without client path re-resolution.
                        source=os.open(src,fs.DIR,dir_fd=srcfd);target=os.open(temp,fs.DIR,dir_fd=dstfd)
                        budget=[0,0]
                        def recurse(a,b,base,depth=0):
                            if depth>64:raise HTTPException(413,'目录深度超过 64 层')
                            for name in os.listdir(a):
                                row=fs.entry(a,name)
                                if row['protected'] or fs.sensitive_absolute(base/name):fs.denied()
                                budget[0]+=1;budget[1]+=row['size'] if row['kind']=='file' else 0
                                if budget[0]>10000 or budget[1]>1024**3:raise HTTPException(413,'目录复制超过上限')
                                if row['kind']=='directory':
                                    os.mkdir(name,0o700,dir_fd=b);x=os.open(name,fs.DIR,dir_fd=a);y=os.open(name,fs.DIR,dir_fd=b)
                                    try:recurse(x,y,base/name,depth+1)
                                    finally:os.close(x);os.close(y)
                                else:copy_file(a,name,b,name)
                        try:recurse(source,target,Path(fs.root(body.root)['path'])/body.path)
                        finally:os.close(source);os.close(target)
                    else:copy_file(srcfd,src,dstfd,temp)
                    fs.check(srcfd,src,body.revision);fs.rename_exclusive(dstfd,temp,dstfd,dst)
                finally:
                    with contextlib.suppress(FileNotFoundError):clean_staging(dstfd,temp)
        audit(body.root,body.path,body.action);return {'ok':True}


class Terminal(BaseModel):
    root:str
    path:str=''
    session:str


@router.post('/terminal')
def terminal(body:Terminal):
    from app import main
    from app.terminal_entry import prepare
    with fs.directory(body.root,body.path) as fd:
        absolute=str(Path(fs.root(body.root)['path'])/body.path)
        result=prepare(body.session,cwd=absolute)
    return dict(result,cwd_applied=result['state']=='created')


@router.get('/trash')
def trash(root:str,path:str=''):
    with fs.directory(root,path) as fd:
        try:child=os.open('.remotehub-trash',fs.DIR,dir_fd=fd)
        except FileNotFoundError:return {'entries':[]}
        try:
            if os.fstat(child).st_uid!=os.getuid():fs.denied()
            rows=[]
            with os.scandir(child) as iterator:
                for row in iterator:
                    if len(rows)>=500:break
                    if len(row.name)<34 or row.name[32]!='-':continue
                    item=fs.entry(child,row.name)
                    item['original_name']=row.name[33:];rows.append(item)
            return {'entries':rows}
        finally:os.close(child)


class Restore(BaseModel):
    root:str
    path:str=''
    name:str
    revision:str
    confirm:str


@router.post('/restore')
def restore(body:Restore):
    import re
    if not re.fullmatch(r'[a-f0-9]{32}-.+',body.name):raise HTTPException(400,'无效回收记录')
    original=body.name[33:];fs.parts(original,False)
    if '/' in original or body.confirm!=original:raise HTTPException(400,'请确认恢复文件名')
    with fs.mutex,fs.directory(body.root,body.path,write=True) as fd:
        child=os.open('.remotehub-trash',fs.DIR,dir_fd=fd)
        try:
            fs.check(child,body.name,body.revision)
            fs.rename_exclusive(child,body.name,fd,original)
        finally:os.close(child)
        with contextlib.suppress(OSError):os.rmdir('.remotehub-trash',dir_fd=fd)
    audit(body.root,'/'.join(filter(None,[body.path,original])),'restore');return {'ok':True}
