#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python - <<'PY'
import os
from pathlib import Path
p=Path('.env')
if not p.exists():
    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:
        f.write('ORH_HOST=127.0.0.1\nORH_PORT=8765\nORH_ZELLIJ_PORT=8082\n')
Path('.runtime').mkdir(mode=0o700,exist_ok=True)
print('Installed. Start: ./scripts/start.sh ; choose your password on the local login page.')
PY
