"""Protect owned SSH terminals even when opened through their native URL."""
from app.ssh import storage as store


def protect_session(request, name):
    import re
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', name):
        return
    records = store.rows('terminal')
    if records and not any(row['session'] == name for row in records):
        from app.ssh.terminals import sessions
        records = sessions()
    if any(row['session'] == name for row in records):
        from app.ssh.api import secure
        # WebSocket URLs use wss instead of https.
        if request.url.scheme == 'wss':
            return
        secure(request)
