"""Capability-style filesystem access: explicit roots, pinned directory FDs, no links.

All traversals use openat/O_NOFOLLOW. Never use a client path in FileResponse,
subprocess cwd, or a recursive shutil operation. Local same-user administrators
can still rename an already-open directory; this is not an OS sandbox.
"""
import contextlib
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
import sys
import threading
from fastapi import HTTPException

mutex=threading.RLock()
DIR=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
BLOCKED={'.git','.ssh','.aws','.gnupg','.codex','.dsh','.kube','.docker','.config','.runtime','.remotehub-trash'}
SENSITIVE={'.npmrc','.pypirc','.netrc','.git-credentials','.credentials.yaml','credentials.json','auth.json','id_rsa','id_ed25519'}
SYSTEM=('/System','/Library','/private','/etc','/usr','/bin','/sbin','/dev','/proc','/sys','/root','/opt','/Applications','/cores','/.vol','/.nofollow','/.resolve')


def protected(parts):
    return any(p.lower() in BLOCKED|SENSITIVE or p.lower()=='.env' or p.lower().startswith('.env.') or p.lower().startswith('.orh-') or p.lower().endswith(('.pem','.key','.p12','.pfx')) for p in parts)


def roots():
    try:
        config=json.loads(os.environ.get('ORH_FILE_ROOTS','[]'))
        if not isinstance(config,list) or not all(isinstance(x,str) and Path(x).expanduser().is_absolute() for x in config):raise ValueError()
        out=[]
        for value in config:
            p=Path(value).expanduser().resolve(strict=True)
            if not p.is_dir() or protected(p.parts):raise ValueError()
            key=hashlib.sha256(str(p).encode()).hexdigest()[:16]
            if not any(x['id']==key for x in out):out.append(dict(id=key,name=p.name or '/',path=str(p)))
        return out
    except (ValueError,TypeError,OSError):raise HTTPException(503,'ORH_FILE_ROOTS 配置无效：请使用存在的非敏感目录绝对路径 JSON 数组')


def sensitive_absolute(path):
    homes=[Path.home()/'Library'/x for x in ('Keychains','Cookies','Safari','Accounts','Mail','Messages','Application Support/Google/Chrome','Application Support/Microsoft Edge','Application Support/Firefox','Application Support/com.apple.TCC','Application Support/@deepseek-ai/dsh-desktop')]
    custom_dsh=Path(os.environ.get('ORH_DSH_HOME',str(Path.home()/'.dsh'))).expanduser().resolve()
    return path==custom_dsh or custom_dsh in path.parents or any(path==p or p in path.parents for p in homes) or any(path==Path(x) or Path(x) in path.parents for x in ('/dev','/proc','/sys','/private/var/db','/private/var/root'))


def readonly(path):
    return any(path==Path(x) or Path(x) in path.parents for x in SYSTEM)


def locate(absolute):
    absolute=Path(absolute).expanduser()
    for item in sorted(roots(),key=lambda r:len(r['path']),reverse=True):
        base=Path(item['path'])
        if absolute==base or base in absolute.parents:
            relative=absolute.relative_to(base).as_posix()
            return dict(root=item['id'],path='' if relative=='.' else relative)
    return None


def root(key):
    return next((x for x in roots() if x['id']==key),None) or denied('目录未授权')


def denied(message='路径或文件受保护'):raise HTTPException(403,message)


def parts(path,allow_root=True):
    if not isinstance(path,str) or len(path)>4096 or '\x00' in path or '\\' in path or path.startswith('/'):
        denied('只允许授权目录内的相对路径')
    chunks=path.split('/') if path else []
    if any(p in ('','..','.') or any(ord(c)<32 for c in p) for p in chunks):denied('无效路径')
    if not chunks and not allow_root:denied('不能修改授权根目录')
    if protected(chunks):denied()
    return chunks


@contextlib.contextmanager
def directory(key,path='',write=False):
    info=root(key);chunks=parts(path)
    absolute=Path(info['path']).joinpath(*chunks)
    if write and readonly(absolute):denied('系统目录只读')
    if sensitive_absolute(absolute):denied('系统或凭据敏感目录受保护')
    # Pin the canonical root without following symlinks in its ancestry either.
    fd=os.open('/',DIR)
    try:
        for name in Path(info['path']).parts[1:]+tuple(chunks):
            new=os.open(name,DIR,dir_fd=fd);os.close(fd);fd=new
        yield fd
    except OSError as e:raise error(e) from e
    finally:os.close(fd)


@contextlib.contextmanager
def parent(key,path,write=False):
    chunks=parts(path,False)
    with directory(key,'/'.join(chunks[:-1]),write=write) as fd:
        if write and readonly(Path(root(key)['path']).joinpath(*chunks)):denied('系统目录只读')
        yield fd,chunks[-1]


def error(e):
    return HTTPException(404 if e.errno==errno.ENOENT else 409 if e.errno in (errno.EEXIST,errno.ENOTEMPTY) else 403,'目标不存在' if e.errno==errno.ENOENT else '文件已存在、被修改或不可安全访问')


def regular(fd):
    s=os.fstat(fd)
    if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1:denied('仅支持普通文件；硬链接和特殊文件受保护')
    return s


def version(s):return hashlib.sha256(f'{s.st_dev}:{s.st_ino}:{s.st_size}:{s.st_mtime_ns}:{s.st_ctime_ns}'.encode()).hexdigest()


def entry(fd,name):
    s=os.stat(name,dir_fd=fd,follow_symlinks=False)
    kind='directory' if stat.S_ISDIR(s.st_mode) else 'file' if stat.S_ISREG(s.st_mode) else 'link' if stat.S_ISLNK(s.st_mode) else 'special'
    return dict(name=name,kind=kind,size=s.st_size,modified=s.st_mtime,revision=version(s),protected=protected([name]) or kind in ('link','special') or (kind=='file' and s.st_nlink!=1))


def check(fd,name,expected):
    value=entry(fd,name)
    if value['protected']:denied()
    if not expected or value['revision']!=expected:raise HTTPException(409,'文件已被修改，请重新读取；未覆盖现有内容')
    return value


@contextlib.contextmanager
def opened(key,path):
    with parent(key,path) as (fd,name):
        try:child=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        except OSError as e:raise error(e) from e
        try:regular(child);yield child
        finally:os.close(child)


def rename_exclusive(srcfd,src,dstfd,dst):
    """Atomic no-replace rename on macOS/Linux; fail closed elsewhere."""
    libc=ctypes.CDLL(None,use_errno=True)
    if sys.platform=='darwin':result=libc.renameatx_np(srcfd,os.fsencode(src),dstfd,os.fsencode(dst),4)
    elif hasattr(libc,'renameat2'):result=libc.renameat2(srcfd,os.fsencode(src),dstfd,os.fsencode(dst),1)
    else:raise HTTPException(501,'本平台缺少原子无覆盖重命名能力')
    if result:
        code=ctypes.get_errno();raise error(OSError(code,os.strerror(code)))


def scan_tree(fd,prefix='',budget=None,base=None):
    if prefix.count('/')>64:raise HTTPException(413,'目录深度超过 64 层')
    budget=budget if budget is not None else [0,0]
    for name in os.listdir(fd):
        item=entry(fd,name)
        if item['protected'] or (base is not None and sensitive_absolute(base/prefix/name)):denied('目录内含受保护文件，未执行整目录操作')
        budget[0]+=1;budget[1]+=item['size'] if item['kind']=='file' else 0
        if budget[0]>10000 or budget[1]>1024**3:raise HTTPException(413,'目录操作上限为 10000 个条目 / 1 GiB，请缩小范围')
        yield prefix+name,item
        if item['kind']=='directory':
            child=os.open(name,DIR,dir_fd=fd)
            try:yield from scan_tree(child,prefix+name+'/',budget,base)
            finally:os.close(child)
