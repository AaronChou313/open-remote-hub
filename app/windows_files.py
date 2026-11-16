"""Windows file operations using native paths and the existing file API model."""
import asyncio
import contextlib
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.routing import APIRoute
from fastapi.responses import FileResponse
from app import file_access as fs
from app.files import Edit, Operation, Restore, Terminal, TEXT_LIMIT, audit

class FileRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def operation(request):
            try:
                return await handler(request)
            except OSError as error:
                raise fs.error(error) from None
        return operation


router = APIRouter(prefix='/api/files', tags=['files'], route_class=FileRoute)


def resolve(root, path='', write=False):
    base = Path(fs.root(root)['path'])
    chunks = fs.parts(path)
    for name in chunks:
        if re.search(r'[<>:"|?*]', name) or name.endswith((' ', '.')) or name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
            raise HTTPException(400, '文件名包含 Windows 保留字符或名称')
    target = base.joinpath(*chunks)
    if not target.resolve().is_relative_to(base.resolve()):
        raise HTTPException(403, '路径超出授权目录')
    current = target
    while current != base:
        if current.exists() or current.is_symlink():
            attributes = current.lstat()
            if current.is_symlink() or getattr(attributes, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
                raise HTTPException(403, '请直接授权目标目录后访问链接内容')
        current = current.parent
    if write and not path:
        raise HTTPException(403, '不能修改授权根目录')
    return target


def entry(path):
    value = path.lstat()
    linked = path.is_symlink() or bool(getattr(value, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))
    kind = 'link' if linked else 'directory' if path.is_dir() else 'file' if path.is_file() else 'special'
    return dict(name=path.name, kind=kind, size=value.st_size, modified=value.st_mtime,
                revision=fs.version(value), symlink=linked,
                protected=linked or fs.protected([path.name]) or kind == 'special', read_only=False, protection_reason='链接或凭据路径受保护' if linked or fs.protected([path.name]) else '')


def check(path, revision):
    if not path.exists():
        raise HTTPException(404, '目标不存在')
    value = entry(path)
    if value['protected']:
        raise HTTPException(403, '目标受保护')
    if not revision or value['revision'] != revision:
        raise HTTPException(409, '文件已被修改，请重新读取')
    return value


@router.get('/roots')
def roots():
    return dict(roots=fs.roots(), default=fs.locate(Path.home()), home=str(Path.home()))


@router.get('/list')
def listing(root: str, path: str = '', offset: int = 0, show_hidden: bool = True, sort: str = 'name', order: str = 'asc'):
    directory = resolve(root, path)
    if not directory.is_dir():
        raise HTTPException(404, '目录不存在')
    if sort not in ('name', 'modified', 'size', 'kind') or order not in ('asc', 'desc') or offset < 0:
        raise HTTPException(400, '无效排序或分页')
    rows = []
    for child in directory.iterdir():
        if child.name.startswith('.orh-') or child.name == '.remotehub-trash' or (not show_hidden and child.name.startswith('.')):
            continue
        with contextlib.suppress(OSError):
            rows.append(entry(child))
        if len(rows) >= 10000:
            break
    key = (lambda row: row['name'].casefold()) if sort == 'name' else (lambda row: (row[sort], row['name'].casefold()))
    rows.sort(key=key, reverse=order == 'desc')
    rows.sort(key=lambda row: row['kind'] != 'directory')
    return dict(root=root, path=path, entries=rows[offset:offset+200], next_offset=offset+200 if len(rows)>offset+200 else None, truncated=len(rows)>=10000, read_only=False, editor_url=None)


@router.get('/text')
def text(root: str, path: str):
    target = resolve(root, path)
    if not target.is_file():
        raise HTTPException(404, '文件不存在')
    before = target.stat()
    with target.open('rb') as source:
        raw = source.read(TEXT_LIMIT + 1)
    if len(raw) > TEXT_LIMIT:
        raise HTTPException(413, '文本上限为 1 MiB')
    try:
        value = raw.decode('utf-8')
        if '\x00' in value:
            raise ValueError()
    except (UnicodeError, ValueError):
        raise HTTPException(415, '不是 UTF-8 文本，请下载文件') from None
    if fs.version(before) != fs.version(target.stat()):
        raise HTTPException(409, '文件正在变更，请重新读取')
    return dict(text=value, revision=fs.version(before), path=path)


@router.post('/text')
def edit(body: Edit):
    if body.confirm != body.path:
        raise HTTPException(400, '请确认覆盖目标')
    target = resolve(body.root, body.path, write=True)
    raw = body.text.encode('utf-8')
    if len(raw) > TEXT_LIMIT:
        raise HTTPException(413, '文本上限为 1 MiB')
    with fs.mutex:
        check(target, body.revision)
        temporary = target.with_name('.orh-' + secrets.token_hex(16))
        try:
            temporary.write_bytes(raw)
            check(target, body.revision)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    audit(body.root, body.path, 'edit')
    return entry(target)


@router.get('/download')
def download(root: str, path: str):
    target = resolve(root, path)
    if not target.is_file():
        raise HTTPException(404, '文件不存在')
    return FileResponse(target, filename=target.name)


@router.post('/upload')
async def upload(request: Request, root: str, path: str, create_parents: bool = False):
    target = resolve(root, path, write=True)
    if create_parents:
        target.parent.mkdir(parents=True, exist_ok=True)
    limit = max(1, min(8192, int(os.environ.get('ORH_MAX_UPLOAD_MB', '2048')))) * 1024**2
    temporary = target.with_name('.orh-' + secrets.token_hex(16))
    total = 0
    try:
        with temporary.open('xb') as output:
            async for chunk in request.stream():
                total += len(chunk)
                if total > limit:
                    raise HTTPException(413, '上传超过配置上限')
                await asyncio.to_thread(output.write, chunk)
        with fs.mutex:
            if target.exists():
                raise HTTPException(409, '文件已存在')
            # Windows rename fails when a destination already exists.
            temporary.rename(target)
    finally:
        temporary.unlink(missing_ok=True)
    audit(root, path, 'upload')
    return entry(target)


@router.post('/operation')
def operate(body: Operation):
    source = resolve(body.root, body.path, write=body.action != 'copy')
    if body.action == 'mkdir':
        if source.exists():
            raise HTTPException(409, '目录已存在')
        source.mkdir()
        return dict(ok=True)
    if body.action not in ('copy','move','rename','delete'):
        raise HTTPException(400, '不支持的文件操作')
    if body.action != 'copy' and body.confirm != body.path:
        raise HTTPException(400, '请确认目标和操作影响')
    with fs.mutex:
        value = check(source, body.revision)
        if source.is_dir():
            for parent, directories, files in os.walk(source, followlinks=False):
                for name in directories + files:
                    child = Path(parent) / name
                    if entry(child)['protected']:
                        raise HTTPException(403, '目录内含受保护对象')
        if body.action == 'delete':
            recycle = source.parent / '.remotehub-trash'
            recycle.mkdir(exist_ok=True)
            name = secrets.token_hex(16) + '-' + source.name
            source.rename(recycle / name)
            audit(body.root, body.path, 'trash')
            return dict(ok=True, trash=name)
        destination = resolve(body.destination_root or body.root, body.destination, write=True)
        if destination == source or source in destination.parents:
            raise HTTPException(400, '目标不能是自身或子目录')
        if destination.exists():
            raise HTTPException(409, '目标已存在')
        if body.action in ('move','rename'):
            source.rename(destination)
        else:
            temporary = destination.with_name('.orh-' + secrets.token_hex(16))
            try:
                if value['kind'] == 'directory':
                    shutil.copytree(source, temporary)
                else:
                    with source.open('rb') as original, temporary.open('xb') as output:
                        shutil.copyfileobj(original, output)
                if destination.exists():
                    raise HTTPException(409, '目标已存在')
                temporary.rename(destination)
            finally:
                if temporary.is_dir():
                    shutil.rmtree(temporary)
                else:
                    temporary.unlink(missing_ok=True)
    audit(body.root, body.path, body.action)
    return dict(ok=True)


@router.get('/search')
def search(root: str, path: str = '', q: str = '', show_hidden: bool = True):
    if not q.strip() or len(q) > 100:
        raise HTTPException(400, '请输入 1–100 字符的搜索词')
    directory = resolve(root, path)
    rows = []
    start = time.monotonic()
    count = 0
    for parent, directories, files in os.walk(directory, followlinks=False):
        directories[:] = [name for name in directories if not entry(Path(parent)/name)['protected'] and (show_hidden or not name.startswith('.'))]
        for name in directories + files:
            count += 1
            target = Path(parent) / name
            if not entry(target)['protected'] and q.casefold() in name.casefold() and (show_hidden or not name.startswith('.')):
                rows.append(dict(entry(target), path=target.relative_to(Path(fs.root(root)['path'])).as_posix()))
            if count >= 10000 or len(rows) >= 100 or time.monotonic() - start > 3:
                return dict(entries=rows, truncated=True)
    return dict(entries=rows, truncated=False)


@router.get('/trash')
def trash(root: str, path: str = ''):
    directory = resolve(root, path) / '.remotehub-trash'
    rows = []
    if directory.is_dir():
        for item in directory.iterdir():
            value = entry(item)
            rows.append(dict(value, original_name=item.name[33:]))
    return dict(entries=rows)


@router.post('/restore')
def restore(body: Restore):
    if not re.fullmatch(r'[a-f0-9]{32}-.+', body.name) or '/' in body.name or '\\' in body.name:
        raise HTTPException(400, '无效回收记录')
    parent = resolve(body.root, body.path)
    source = parent / '.remotehub-trash' / body.name
    target_name = body.name[33:]
    if body.confirm != target_name:
        raise HTTPException(400, '请确认恢复目标')
    target = resolve(body.root, '/'.join(filter(None, [body.path, target_name])), write=True)
    with fs.mutex:
        check(source, body.revision)
        if target.exists():
            raise HTTPException(409, '恢复目标已存在')
        source.rename(target)
    return dict(ok=True)


@router.post('/terminal')
def terminal(body: Terminal):
    from app.conpty import prepare
    from app.modules import require
    require('terminal')
    directory = resolve(body.root, body.path)
    if not directory.is_dir():
        raise HTTPException(400, '请选择目录')
    return dict(terminal=prepare(body.session, directory))
