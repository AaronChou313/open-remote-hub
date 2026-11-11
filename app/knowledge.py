"""Directory-backed Markdown notebooks using the existing file access layer."""
import os
from pathlib import Path
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import file_access as fs, files, workspace_store as store

router = APIRouter(prefix='/api/knowledge', tags=['knowledge'])
MARKDOWN = {'.md', '.markdown'}


def audit(key, action):
    from app.main import audit as record
    record('knowledge', key, action)


def join(base, relative):
    return '/'.join(filter(None, (base, relative)))


def location(directory):
    path = Path(directory).expanduser()
    if not path.is_absolute():
        raise HTTPException(400, '请输入目录绝对路径，或使用 ~/ 开头的路径')
    value = fs.locate(path)
    if not value:
        raise HTTPException(403, '此目录不在当前文件访问范围内')
    fs.parts(value['path'])
    return value


def ensure_directory(root, path):
    parts = fs.parts(path)
    for index, name in enumerate(parts):
        with fs.directory(root, '/'.join(parts[:index]), write=True) as fd:
            try:
                os.mkdir(name, mode=0o700, dir_fd=fd)
            except FileExistsError:
                pass
        with fs.directory(root, '/'.join(parts[:index + 1])):
            pass


def book(key):
    value = store.get('knowledge', key)
    with fs.directory(value['root'], value['path']):
        pass
    return value


def absolute(value):
    return str(Path(fs.root(value['root'])['path']) / value['path'])


def note_path(value, path):
    fs.parts(path, False)
    if Path(path).suffix.lower() not in MARKDOWN:
        raise HTTPException(400, '笔记使用 .md 或 .markdown 扩展名')
    return join(value['path'], path)


class Library(BaseModel):
    directory: str = Field(min_length=1, max_length=4096)
    name: str = Field(default='', max_length=100)
    create: bool = False


@router.get('')
def libraries():
    result = []
    for value in store.rows('knowledge'):
        try:
            with fs.directory(value['root'], value['path']):
                pass
            result.append(dict(value, directory=absolute(value), available=True))
        except (HTTPException, OSError) as error:
            result.append(dict(value, directory=value['directory'], available=False,
                               error=error.detail if isinstance(error, HTTPException) else '目录不可访问'))
    return dict(libraries=sorted(result, key=lambda row: row['name'].casefold()))


@router.post('')
def add_library(body: Library):
    value = location(body.directory)
    name = body.name.strip() or Path(body.directory).expanduser().name or '知识库'
    with fs.mutex:
        if any(row['root'] == value['root'] and row['path'] == value['path'] for row in store.rows('knowledge')):
            raise HTTPException(409, '该目录已添加为知识库')
        if body.create:
            ensure_directory(value['root'], value['path'])
        with fs.directory(value['root'], value['path']):
            pass
        result = store.save('knowledge', dict(value, name=name, directory=absolute(value)))
    audit(result['id'], 'create' if body.create else 'add-directory')
    return result


class LibraryChange(BaseModel):
    revision: str
    action: str = 'update'
    name: str = Field(default='', max_length=100)
    directory: str = Field(default='', max_length=4096)
    confirm: str = ''


@router.post('/{key}')
def change_library(key: str, body: LibraryChange):
    with fs.mutex:
        value = store.get('knowledge', key)
        if value['revision'] != body.revision:
            raise HTTPException(409, '知识库已修改，请刷新后重试')
        if body.action in ('remove', 'trash'):
            if body.action == 'trash':
                if body.confirm != key:
                    raise HTTPException(400, '请确认要删除的知识库目录')
                with fs.parent(value['root'], value['path']) as (fd, name):
                    entry = fs.entry(fd, name)
                files.operate(files.Operation(root=value['root'], path=value['path'], action='delete',
                                               revision=entry['revision'], confirm=value['path']))
            store.remove('knowledge', key, body.revision)
            audit(key, body.action)
            return dict(ok=True)
        if body.action != 'update':
            raise HTTPException(400, '不支持的知识库操作')
        target = location(body.directory) if body.directory else dict(root=value['root'], path=value['path'])
        with fs.directory(target['root'], target['path']):
            pass
        if any(row['id'] != key and row['root'] == target['root'] and row['path'] == target['path']
               for row in store.rows('knowledge')):
            raise HTTPException(409, '该目录已添加为知识库')
        result = store.save('knowledge', dict(target, name=body.name.strip() or value['name'],
                                              directory=absolute(target)), key, body.revision)
    audit(key, 'update')
    return result


@router.get('/{key}/tree')
def tree(key: str):
    value = book(key)
    entries, warnings, visited = [], [], set()
    started, examined = time.monotonic(), 0
    truncated = False

    def walk(relative, depth=0):
        nonlocal examined, truncated
        if depth > 64:
            truncated = True
            return
        with fs.directory(value['root'], join(value['path'], relative)) as fd:
            state = os.fstat(fd)
            identity = (state.st_dev, state.st_ino)
            if identity in visited:
                return
            visited.add(identity)
            with os.scandir(fd) as iterator:
                children = []
                for child in iterator:
                    examined += 1
                    if examined > 10000 or time.monotonic() - started > 3:
                        truncated = True
                        break
                    if child.name in ('.git', '.remotehub-trash') or child.name.startswith('.orh-'):
                        continue
                    try:
                        row = fs.entry(fd, child.name)
                    except FileNotFoundError:
                        continue
                    if row['protected']:
                        continue
                    path = join(relative, row['name'])
                    if row['kind'] == 'directory':
                        entries.append(dict(row, path=path))
                        children.append(path)
                    elif row['kind'] == 'file' and Path(row['name']).suffix.lower() in MARKDOWN:
                        entries.append(dict(row, path=path))
            for path in children:
                if truncated:
                    break
                try:
                    walk(path, depth + 1)
                except (HTTPException, OSError):
                    warnings.append(path)
    walk('')
    return dict(value, directory=absolute(value), entries=sorted(entries, key=lambda row: row['path'].casefold()),
                count=sum(row['kind'] == 'file' for row in entries), truncated=truncated, warnings=warnings)


@router.get('/{key}/note')
def read_note(key: str, path: str):
    value = book(key)
    full = note_path(value, path)
    with fs.parent(value['root'], full) as (fd, name):
        entry = fs.entry(fd, name)
    return dict(files.text(value['root'], full), path=path, entry_revision=entry['revision'],
                name=Path(path).name, modified=entry['modified'])


class Note(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    text: str = Field(default='', max_length=files.TEXT_LIMIT)
    revision: str = ''


@router.post('/{key}/note')
def save_note(key: str, body: Note):
    value = book(key)
    full = note_path(value, body.path)
    if body.revision:
        return files.edit(files.Edit(root=value['root'], path=full, text=body.text,
                                     revision=body.revision, confirm=full))
    if len(body.text.encode('utf-8')) > files.TEXT_LIMIT:
        raise HTTPException(413, '文本上限为 1 MiB')
    with fs.mutex:
        ensure_directory(value['root'], str(Path(full).parent) if '/' in full else '')
        return files.create_text(value['root'], full, body.text)


class NoteOperation(BaseModel):
    path: str
    revision: str
    action: str
    destination: str = ''
    confirm: str = ''


@router.post('/{key}/operation')
def note_operation(key: str, body: NoteOperation):
    value = book(key)
    source = note_path(value, body.path)
    with fs.parent(value['root'], source) as (fd, name):
        if fs.entry(fd, name)['kind'] != 'file':
            raise HTTPException(400, '请选择 Markdown 笔记文件')
    if body.action not in ('rename', 'delete'):
        raise HTTPException(400, '不支持的笔记操作')
    if body.action == 'delete' and body.confirm != body.path:
        raise HTTPException(400, '请确认删除的笔记')
    destination = note_path(value, body.destination) if body.action == 'rename' else ''
    return files.operate(files.Operation(root=value['root'], path=source, revision=body.revision,
                                         action=body.action, destination=destination, confirm=source))


@router.get('/{key}/asset')
def asset(key: str, request: Request, path: str):
    value = book(key)
    fs.parts(path, False)
    return files.download(request, value['root'], join(value['path'], path))
