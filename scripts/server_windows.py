"""Windows foreground entry: install compatibility shims, then run the server."""
import runpy
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from app.windows_compat import install

install()
runpy.run_path(str(root / 'scripts' / 'server.py'), run_name='__main__')
