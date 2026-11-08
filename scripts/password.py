#!/usr/bin/env python3
"""Local recovery/setup: never pass passwords as command-line arguments."""
import getpass
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from app import passwords

if __name__ == '__main__':
    password = getpass.getpass('New RemoteHub password (at least 10 characters): ')
    if password != getpass.getpass('Repeat password: '):
        raise SystemExit('Passwords differ; nothing changed.')
    passwords.save(password)
    print('Password saved. Existing browser logins are now invalid.')
