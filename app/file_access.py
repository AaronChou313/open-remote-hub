"""Configured file policy with pinned descriptors and OS-account permissions."""
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


def unrestricted():
    policy=os.environ.get('ORH_FILE_POLICY','protected')
    if policy not in ('protected','unrestricted'):raise HTTPException(503,'ORH_FILE_POLICY 必须为 protected 或 unrestricted')
    return policy=='unrestricted'


def protected(parts):
    if unrestricted():return False
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
    except (ValueError,TypeError,OSError):raise HTTPException(503,'ORH_FILE_ROOTS 配置无效：请使用存在且符合访问策略的目录绝对路径 JSON 数组')


def sensitive_absolute(path):
    if unrestricted():return False
    homes=[Path.home()/'Library'/x for x in ('Keychains','Cookies','Safari','Accounts','Mail','Messages','Application Support/Google/Chrome','Application Support/Microsoft Edge','Application Support/Firefox','Application Support/com.apple.TCC','Application Support/@deepseek-ai/dsh-desktop')]
    custom_dsh=Path(os.environ.get('ORH_DSH_HOME',str(Path.home()/'.dsh'))).expanduser().resolve()
    return path==custom_dsh or custom_dsh in path.parents or any(path==p or p in path.parents for p in homes) or any(path==Path(x) or Path(x) in path.parents for x in ('/dev','/proc','/sys','/private/var/db','/private/var/root'))


def readonly(path):
    if unrestricted():return False
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
    if unrestricted():
        try:absolute=absolute.resolve(strict=True)
        except (OSError,RuntimeError) as e:raise error(e) from e
        if locate(absolute) is None:denied('软链接目标不在授权目录内')
        components=absolute.parts[1:]
    else:components=Path(info['path']).parts[1:]+tuple(chunks)
    # Pin the canonical root without following symlinks in its ancestry either.
    fd=os.open('/',DIR)
    try:
        for name in components:
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
    if isinstance(e,PermissionError) or getattr(e,'errno',None) in (errno.EACCES,errno.EPERM):
        message='操作系统拒绝访问，请检查当前服务账户的文件权限'
        if sys.platform=='darwin':message+='；下载、桌面、文稿等目录需在 Mac「系统设置 → 隐私与安全性 → 完全磁盘访问权限」中授权运行 RemoteHub 的 Python.app，随后重启控制台'
        return HTTPException(403,message)
    if isinstance(e,RuntimeError) or getattr(e,'errno',None)==errno.ELOOP:return HTTPException(409,'软链接循环或目标发生变化，请刷新后重试')
    return HTTPException(404 if e.errno==errno.ENOENT else 409 if e.errno in (errno.EEXIST,errno.ENOTEMPTY) else 403,'目标不存在' if e.errno==errno.ENOENT else '文件已存在、被修改或不可安全访问')


def regular(fd):
    s=os.fstat(fd)
    if not stat.S_ISREG(s.st_mode):denied('此操作仅支持普通文件')
    if s.st_nlink!=1 and not unrestricted():denied('硬链接受保护')
    return s


def version(s):return hashlib.sha256(f'{s.st_dev}:{s.st_ino}:{s.st_size}:{s.st_mtime_ns}:{s.st_ctime_ns}'.encode()).hexdigest()


def entry(fd,name):
    s=os.stat(name,dir_fd=fd,follow_symlinks=False)
    target=s;symlink=stat.S_ISLNK(s.st_mode)
    if symlink and unrestricted():
        with contextlib.suppress(OSError):target=os.stat(name,dir_fd=fd)
    kind='directory' if stat.S_ISDIR(target.st_mode) else 'file' if stat.S_ISREG(target.st_mode) else 'link' if symlink else 'special'
    return dict(name=name,kind=kind,size=target.st_size,modified=target.st_mtime,revision=version(s),symlink=symlink,protected=protected([name]) or kind=='special' or (not unrestricted() and (symlink or (kind=='file' and s.st_nlink!=1))))


def check(fd,name,expected):
    value=entry(fd,name)
    if value['protected']:denied()
    if not expected or value['revision']!=expected:raise HTTPException(409,'文件已被修改，请重新读取；未覆盖现有内容')
    return value


@contextlib.contextmanager
def opened(key,path):
    key,path=file_target(key,path)
    with parent(key,path) as (fd,name):
        try:child=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        except OSError as e:raise error(e) from e
        try:regular(child);yield child
        finally:os.close(child)


def file_target(key,path):
    """Follow a file link only in unrestricted mode, within configured roots."""
    parts(path,False)
    if not unrestricted():return key,path
    try:absolute=(Path(root(key)['path'])/path).resolve(strict=True)
    except (OSError,RuntimeError) as e:raise error(e) from e
    location=locate(absolute)
    if location is None:denied('软链接目标不在授权目录内')
    return location['root'],location['path']


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
        if item['kind']=='directory' and not item['symlink']:
            child=os.open(name,DIR,dir_fd=fd)
            try:yield from scan_tree(child,prefix+name+'/',budget,base)
            finally:os.close(child)
