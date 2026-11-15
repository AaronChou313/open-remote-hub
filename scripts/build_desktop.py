"""Build a self-contained macOS DMG or Debian desktop/Agent installer."""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / 'VERSION').read_text().strip()
ARCH = 'arm64' if platform.machine().lower() in ('arm64','aarch64') else 'amd64'
BUILD = ROOT / 'build'
DIST = ROOT / 'dist'


def run(*arguments, **options):
    options.setdefault('cwd', ROOT)
    subprocess.run(list(map(str, arguments)), check=True, **options)


def main():
    BUILD.mkdir(exist_ok=True)
    DIST.mkdir(exist_ok=True)
    (ROOT / 'bin').mkdir(exist_ok=True)
    go = shutil.which('go')
    if not go:
        raise SystemExit('Go is required to build the bundled Mesh engine')
    run(go, 'build', '-trimpath', '-ldflags=-s -w', '-o', ROOT/'bin/orh-mesh', './cmd/orh-mesh', cwd=ROOT/'mesh')
    run(sys.executable, 'mesh/packaging/notices.py')
    if sys.platform == 'darwin':
        from PIL import Image
        Image.open(ROOT/'static/orh-logo.png').save(BUILD/'orh.icns')
    run(sys.executable, '-m', 'PyInstaller', 'desktop/orh.spec', '--noconfirm', '--clean', '--distpath', BUILD/'desktop', '--workpath', BUILD/'pyinstaller')
    if sys.platform == 'darwin':
        stage = BUILD/'dmg'
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir()
        shutil.copytree(BUILD/'desktop/OpenRemoteHub.app', stage/'OpenRemoteHub.app', symlinks=True)
        (stage/'Applications').symlink_to('/Applications')
        target = DIST/f'OpenRemoteHub-{VERSION}-macos-{ARCH}.dmg'
        target.unlink(missing_ok=True)
        run('hdiutil', 'create', '-volname', 'OpenRemoteHub', '-srcfolder', stage, '-ov', '-format', 'UDZO', target)
    elif sys.platform.startswith('linux'):
        stage = BUILD/'deb'
        shutil.rmtree(stage, ignore_errors=True)
        app = stage/'usr/lib/openremotehub'
        app.parent.mkdir(parents=True)
        shutil.copytree(BUILD/'desktop/OpenRemoteHub', app, symlinks=True)
        (stage/'usr/bin').mkdir(parents=True)
        (stage/'usr/bin/openremotehub').symlink_to('../lib/openremotehub/OpenRemoteHub')
        desktop = stage/'usr/share/applications/openremotehub.desktop'
        desktop.parent.mkdir(parents=True)
        desktop.write_text('[Desktop Entry]\nType=Application\nName=OpenRemoteHub\nExec=/usr/bin/openremotehub\nIcon=openremotehub\nTerminal=false\nCategories=Network;System;\n')
        icons = stage/'usr/share/icons/hicolor/256x256/apps'
        icons.mkdir(parents=True)
        shutil.copy2(ROOT/'static/orh-logo.png', icons/'openremotehub.png')
        autostart = stage/'etc/xdg/autostart'
        autostart.mkdir(parents=True)
        (autostart/'openremotehub.desktop').write_text('[Desktop Entry]\nType=Application\nName=OpenRemoteHub background\nExec=/usr/bin/openremotehub --tray\nTerminal=false\nX-GNOME-Autostart-enabled=true\n')
        control = stage/'DEBIAN'
        control.mkdir()
        (control/'control').write_text(f'Package: openremotehub\nVersion: {VERSION}\nArchitecture: {ARCH}\nMaintainer: OpenRemoteHub\nSection: net\nPriority: optional\nDepends: libnss3, libxkbcommon0, libxcb-cursor0, libasound2, libegl1, libgl1, libdbus-1-3, libxcomposite1, libxdamage1, libxrandr2, libxtst6, libxkbcommon-x11-0\nDescription: OpenRemoteHub desktop Client, Agent and private Mesh\n')
        run('dpkg-deb', '--build', '--root-owner-group', stage, DIST/f'OpenRemoteHub-{VERSION}-linux-{ARCH}.deb')
    else:
        raise SystemExit('Use windows/build.ps1 on Windows')


if __name__ == '__main__':
    main()
