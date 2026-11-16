"""Optional host capabilities, enabled independently of the Client and Mesh."""
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import threading

from fastapi import APIRouter, Depends, HTTPException
from app.remote_connect.api import administrator

lock = threading.RLock()
router = APIRouter(prefix='/api/modules', tags=['modules'], dependencies=[Depends(administrator)])
CATALOG = {
    'terminal': ('终端', 'zellij', 'terminal', ('Darwin', 'Linux', 'Windows')),
    'files': ('文件管理', 'files', 'files', ('Darwin', 'Linux', 'Windows')),
    'docker': ('Docker', 'docker', 'docker', ('Darwin', 'Linux', 'Windows')),
    'desktop': ('远程桌面', 'rustdesk', 'desktop', ('Darwin', 'Linux', 'Windows')),
    'ssh': ('SSH 管理', 'ssh', 'ssh', ('Darwin', 'Linux')),
    'services': ('进程与服务', None, 'services', ('Darwin', 'Linux', 'Windows')),
    'projects': ('项目', None, 'projects', ('Darwin', 'Linux')),
    'environments': ('开发环境', None, 'environments', ('Darwin', 'Linux')),
    'knowledge': ('知识库', 'files', 'knowledge', ('Darwin', 'Linux')),
    'dsh': ('DSH 工作台', 'dsh', 'dsh', ('Darwin', 'Linux')),
    'proxy': ('网络代理', 'proxy', 'proxy', ('Darwin', 'Linux')),
}
GUIDES = {
    'zellij': ('安装 Zellij 后重新检测。', 'https://zellij.dev/documentation/installation', 'brew install zellij'),
    'conpty': ('Windows 安装包自带 ConPTY 后端。源码安装请安装 pywinpty。', 'https://github.com/andfoy/pywinpty', 'python -m pip install pywinpty'),
    'docker': ('安装 Docker 并启动 Docker Engine，然后重新检测。', 'https://docs.docker.com/get-started/get-docker/', ''),
    'rustdesk': ('安装 RustDesk 并启用直连访问；被控 macOS 还需屏幕录制和辅助功能权限。', 'https://rustdesk.com/download', ''),
    'ssh': ('安装 OpenSSH 客户端。', 'https://www.openssh.com/portable.html', ''),
    'git': ('安装 Git 后重新检测。', 'https://git-scm.com/downloads', ''),
    'dsh': ('安装 DeepSeek Harness 后配置 ORH_DSH_BIN，然后重新检测。', 'https://www.npmjs.com/package/@deepseek-ai/dsh', ''),
    'proxy': ('启用后在「网络连接 → 网络代理」点击「安装 Mihomo」，并在目标主机完成一次管理员授权。', '', ''),
}


def state_path():
    from app.main import DATA
    return DATA / 'modules.json'


def load():
    path = state_path()
    with lock:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
        # Existing installations retain their available entry points. A fresh
        # Agent initializes this file before its first account login.
        legacy = any((path.parent / name).exists() for name in ('credentials.json', 'cloud-binding.json'))
        value = {name: legacy for name in CATALOG}
        save(value)
        return value


def save(value):
    path = state_path()
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(path)


def enabled(identifier):
    return bool(load().get(identifier, False))


def dependency(identifier):
    if identifier is None or identifier == 'files':
        return dict(available=True, detail='宿主机内置能力')
    if identifier == 'conpty':
        present = importlib.util.find_spec('winpty') is not None
        return dict(available=present, detail='ConPTY / PowerShell' if present else '缺少 pywinpty')
    if identifier == 'dsh':
        from app.dsh import installation
        value = installation()
        return dict(available=bool(value), detail='DeepSeek Harness' if value else '尚未安装 DeepSeek Harness')
    if identifier == 'proxy':
        from app.proxy_manager import settings
        present = bool(settings() or os.environ.get('ORH_CLASH_SOCKET') or os.environ.get('ORH_CLASH_URL'))
        return dict(available=present, detail='Mihomo broker' if present else '尚未安装代理 broker')
    binary = shutil.which(identifier)
    if identifier == 'rustdesk' and not binary:
        if platform.system() == 'Darwin':
            binary = next((str(path) for path in (Path('/Applications/RustDesk.app/Contents/MacOS/RustDesk'), Path('/Applications/RustDesk.app/Contents/MacOS/rustdesk')) if path.exists()), None)
        elif platform.system() == 'Windows':
            binary = next((str(Path(base) / 'RustDesk/rustdesk.exe') for base in (os.environ.get('ProgramFiles', ''), os.environ.get('ProgramFiles(x86)', '')) if base and (Path(base) / 'RustDesk/rustdesk.exe').exists()), None)
    if not binary:
        return dict(available=False, detail='未安装 ' + identifier)
    if identifier == 'docker':
        try:
            result = subprocess.run([binary, 'info', '--format', '{{.ServerVersion}}'], capture_output=True, text=True, timeout=6)
            return dict(available=result.returncode == 0, detail=result.stdout.strip() if result.returncode == 0 else 'Docker Engine 未启动或当前账户无法访问')
        except (OSError, subprocess.TimeoutExpired):
            return dict(available=False, detail='Docker Engine 无法访问')
    return dict(available=True, detail=binary)


def status(identifier, values=None):
    if identifier not in CATALOG:
        raise HTTPException(404, '功能模块不存在')
    name, requirement, entry, platforms = CATALOG[identifier]
    system = platform.system()
    if identifier == 'terminal' and system == 'Windows':
        requirement = 'conpty'
    supported = system in platforms
    active = (values if values is not None else load()).get(identifier, False)
    check = dependency(requirement) if supported else dict(available=False, detail='此模块尚未支持 ' + system)
    hint, url, command = GUIDES.get(requirement, ('', '', ''))
    if requirement == 'zellij' and system == 'Linux':
        command = ''
    state = 'disabled' if not active else 'error' if not supported else 'ready' if check['available'] else 'missing_dependency'
    return dict(id=identifier, name=name, enabled=active, supported=supported, platforms=platforms,
                state=state, dependency=check, entry=entry, guide=dict(text=hint, url=url, command=command))


def require(identifier):
    if not enabled(identifier):
        raise HTTPException(409, dict(code='module_disabled', module=identifier,
                            message=CATALOG[identifier][0] + '尚未启用，请在功能管理中启用', state='disabled'))


def for_path(path):
    groups = {
        'terminal': ('/api/zellij', '/api/zellij-web', '/terminal'),
        'files': ('/api/files',), 'docker': ('/api/docker',),
        'desktop': ('/api/remote-connect/rustdesk',), 'ssh': ('/api/ssh',),
        'services': ('/api/local-services', '/api/services', '/api/tasks'),
        'projects': ('/api/projects',), 'environments': ('/api/environments',),
        'knowledge': ('/api/knowledge',), 'dsh': ('/api/dsh',), 'proxy': ('/api/proxy',),
    }
    return next((name for name, prefixes in groups.items() if any(path == prefix or path.startswith(prefix + '/') for prefix in prefixes)), None)


@router.get('')
def listing():
    values = load()
    return dict(modules=[status(identifier, values) for identifier in CATALOG])


@router.get('/{identifier}')
def detail(identifier: str):
    return status(identifier)


@router.post('/{identifier}/enable')
def enable(identifier: str):
    value = status(identifier)
    if not value['supported']:
        raise HTTPException(409, value['dependency']['detail'])
    # Keep the user's intent when an external dependency is missing. The UI
    # reports missing_dependency and offers installation plus another check.
    with lock:
        values = load()
        values[identifier] = True
        save(values)
    if identifier == 'dsh':
        os.environ['ORH_DSH_ENABLED'] = '1'
    return status(identifier)


@router.post('/{identifier}/disable')
def disable(identifier: str):
    status(identifier)
    with lock:
        values = load()
        values[identifier] = False
        save(values)
    return status(identifier)
