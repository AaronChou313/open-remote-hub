"""Child entry points for source and frozen desktop installations."""
from pathlib import Path
import shutil
import sys
from fastapi import HTTPException


def script(name, *arguments):
    from app.main import ROOT
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--run-script', name, *map(str, arguments)]
    return [sys.executable, str(ROOT / 'scripts' / name), *map(str, arguments)]


def interpreter():
    if not getattr(sys, 'frozen', False):
        return sys.executable
    binary = shutil.which('python3') or shutil.which('python')
    if not binary:
        raise HTTPException(503, '创建 Python 环境需要先安装宿主机 Python')
    return binary
