"""Compatibility entry for old saved Zellij layouts; no permission overrides."""
import json
import os
from pathlib import Path

if __name__ == '__main__':
    root=Path(__file__).resolve().parent.parent
    try:thread=json.loads((root/'.runtime/cli-history.json').read_text()).get('thread_id')
    except (OSError,ValueError):thread=None
    args=['codex']
    if thread:args+=['resume',thread]
    os.execvp('codex',args)
