"""Protect owned SSH terminals even when opened through their native URL."""
from app.ssh import storage as store


def protect_session(request, name):
    if not name.startswith('ssh-'):
        return
    if any(row['session'] == name for row in store.rows('terminal')):
        from app.ssh.api import secure
        # WebSocket URLs use wss instead of https.
        if request.url.scheme == 'wss':
            return
        secure(request)
