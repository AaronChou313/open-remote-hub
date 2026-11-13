import os
from pathlib import Path

import shutil
import sys

BINARY = Path(os.environ.get('ORH_RUSTDESK_BIN', '/Applications/RustDesk.app/Contents/MacOS/RustDesk' if sys.platform == 'darwin' else shutil.which('rustdesk') or '/usr/bin/rustdesk'))
SOCKET = Path(f'/tmp/RustDesk-{os.getuid()}/ipc')


def data_dir():
    from app.main import DATA
    path = DATA / 'remote-connect'
    path.mkdir(mode=0o700, exist_ok=True)
    return path


# These keys are the current user's native RustDesk Options. Unknown native
# options remain in memory and are merged back unchanged when saving a patch.
OPTIONS = {
    'custom-rendezvous-server': ('text', ''),
    'relay-server': ('text', ''),
    'api-server': ('url', ''),
    'key': ('text', ''),
    'direct-server': ('bool', ''),
    'direct-access-port': ('port', ''),
    'enable-keyboard': ('bool', ''),
    'enable-clipboard': ('bool', ''),
    'enable-file-transfer': ('bool', ''),
    'enable-audio': ('bool', ''),
    'approve-mode': ('choice', ('password', 'click', 'password-click', '')),
    'verification-method': ('choice', ('use-temporary-password', 'use-permanent-password', 'use-both-passwords', '')),
    'temporary-password-length': ('choice', ('6', '8', '10', '')),
}
