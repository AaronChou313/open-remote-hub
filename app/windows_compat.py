"""Minimal Unix compatibility shims so the console can start on Windows.

The Windows edition keeps the portable console and the ORN data plane. Unix-only
features (PTY terminals, SSH, fd-relative file operations) are hidden in the UI
and fail explicitly if called, instead of preventing the server from starting.
"""
import os
import signal
import sys
import types


def _stub(name, **attributes):
    if sys.modules.get(name) is not None:
        return
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    sys.modules[name] = module


def _unsupported(label):
    def call(*args, **kwargs):
        raise OSError(f'{label} is not available on Windows')
    return call


def install():
    """Install shims once. Returns True when running on Windows."""
    if os.name != 'nt':
        return False
    _stub('fcntl', LOCK_EX=2, LOCK_SH=1, LOCK_UN=8, LOCK_NB=4,
          flock=_unsupported('fcntl.flock'), lockf=_unsupported('fcntl.lockf'))
    _stub('pty', openpty=_unsupported('pty.openpty'), fork=_unsupported('pty.fork'))
    _stub('termios', TCSANOW=0, TCSAFLUSH=0, ECHO=0,
          tcgetattr=_unsupported('termios.tcgetattr'), tcsetattr=_unsupported('termios.tcsetattr'))
    for name in ('getuid', 'getgid', 'geteuid', 'getegid'):
        if not hasattr(os, name):
            setattr(os, name, lambda: 0)
    for name in ('O_NOFOLLOW', 'O_DIRECTORY', 'O_CLOEXEC', 'O_NONBLOCK'):
        if not hasattr(os, name):
            setattr(os, name, 0)
    if not hasattr(signal, 'SIGKILL'):
        signal.SIGKILL = signal.SIGTERM
    if not hasattr(os, 'killpg'):
        def killpg(pid, sig):
            os.kill(pid, sig)
        os.killpg = killpg
    return True
