"""Locate desktop tools installed after the Agent started, including per-user installs."""
import os
from pathlib import Path
import shutil
import sys


def windows_install_directory(name):
    import winreg
    uninstall = r'Software\Microsoft\Windows\CurrentVersion\Uninstall'
    for hive, location in ((winreg.HKEY_CURRENT_USER, uninstall),
                           (winreg.HKEY_LOCAL_MACHINE, uninstall),
                           (winreg.HKEY_LOCAL_MACHINE, r'Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall')):
        try:
            with winreg.OpenKey(hive, location) as parent:
                for index in range(winreg.QueryInfoKey(parent)[0]):
                    try:
                        with winreg.OpenKey(parent, winreg.EnumKey(parent, index)) as key:
                            label = winreg.QueryValueEx(key, 'DisplayName')[0]
                            if label.casefold() == name.casefold():
                                value = winreg.QueryValueEx(key, 'InstallLocation')[0].strip('" ')
                                if value:
                                    return Path(os.path.expandvars(value))
                    except OSError:
                        continue
        except OSError:
            continue
    return None


def docker_desktop():
    if sys.platform != 'win32':
        return None
    folders = [windows_install_directory('Docker Desktop')]
    for variable, relative in (('LOCALAPPDATA', 'Programs/DockerDesktop'), ('ProgramFiles', 'Docker/Docker')):
        if os.environ.get(variable):
            folders.append(Path(os.environ[variable]) / relative)
    return next((folder / 'Docker Desktop.exe' for folder in folders if folder and (folder / 'Docker Desktop.exe').is_file()), None)


def find(name):
    binary = shutil.which(name)
    if binary:
        return binary
    if sys.platform != 'win32':
        return None
    candidates = []
    if name == 'docker':
        desktop = docker_desktop()
        if desktop:
            candidates.append(desktop.parent / 'resources/bin/docker.exe')
    elif name == 'rustdesk':
        folder = windows_install_directory('RustDesk')
        if folder:
            candidates.append(folder / 'rustdesk.exe')
        for variable, relative in (('ProgramFiles', 'RustDesk/rustdesk.exe'),
                                   ('ProgramFiles(x86)', 'RustDesk/rustdesk.exe'),
                                   ('LOCALAPPDATA', 'Programs/RustDesk/rustdesk.exe')):
            if os.environ.get(variable):
                candidates.append(Path(os.environ[variable]) / relative)
    return next((str(path) for path in candidates if path.is_file()), None)
