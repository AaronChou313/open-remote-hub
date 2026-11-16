"""Open the desktop Client while retaining the separately managed Agent."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    try:
        import webview
    except ImportError:
        raise SystemExit('请先安装客户端依赖：.venv/bin/pip install -r client/requirements.txt') from None
    from app.main import NETWORK, PORT, DATA
    from app.desktop_client import run

    subprocess.run([sys.executable, str(ROOT / 'scripts/control.py'), 'start'], cwd=ROOT, check=True)
    run(NETWORK.local_url(PORT).rstrip('/') + '/client', DATA / 'client-webview')


if __name__ == '__main__':
    main()
