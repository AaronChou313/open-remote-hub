"""Bounded CLI discovery with an explicitly labelled host-evidence fallback.

A stalled Zellij IPC peer must not hide every other session. The fallback does
not ping, attach to, restart, or terminate any session or child process.
"""
import os
from pathlib import Path
import re
import psutil
from app.platforms import command


def cache_roots():
    return [Path.home()/'Library/Caches/org.Zellij-Contributors.Zellij',
            Path(os.environ.get('XDG_CACHE_HOME',str(Path.home()/'.cache')))/'zellij']


def host_sessions():
    live = {}
    for p in psutil.process_iter(['name', 'cmdline', 'uids', 'status']):
        try:
            info = p.info
            argv = info['cmdline'] or []
            if info['name'] != 'zellij' or '--server' not in argv or info['status'] == psutil.STATUS_ZOMBIE:
                continue
            if info['uids'] and info['uids'].real != os.getuid():
                continue
            index = argv.index('--server')
            if index + 1 >= len(argv):
                continue
            name = Path(argv[index + 1]).name
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', name):
                continue
            orphan=not Path(argv[index+1]).exists() and not p.children(recursive=True)
            live[name] = dict(name=name,status='exited' if orphan else 'running',pid=p.pid,created=p.create_time(),orphan=orphan,
                              detail='会话已退出，服务进程仍在清理' if orphan else f'Zellij PID {p.pid}')
        except (psutil.Error, OSError, ValueError):
            continue
    roots = cache_roots()
    entries = dict(live)
    for root in roots:
        for layout in root.glob('*/session_info/*/session-layout.kdl'):
            name = layout.parent.name
            if name not in entries and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', name):
                entries[name] = dict(name=name, status='exited', detail='本机保存的 Zellij 布局；未发现对应活动服务进程')
    return sorted(entries.values(), key=lambda s: (s['status'] != 'running', s['name']))


def discover():
    try:
        text = command(['zellij', 'list-sessions', '-n'], timeout=2)
        entries = [dict(name=x.split(' [')[0], status='exited' if '(EXITED' in x else 'running', detail=x)
                   for x in text.splitlines() if ' [' in x]
        return entries, None
    except RuntimeError as e:
        if 'No active' in str(e) or 'No sessions' in str(e):
            return [], None
        return host_sessions(), 'Zellij 会话查询命令超时或不可用。以下为宿主机进程和已保存布局的真实记录；进程存活不代表终端交互正常。未重启或结束现有会话。'
