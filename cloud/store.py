from contextlib import contextmanager
"""SQLite account, binding and one-use ticket storage."""
import hashlib
import os
from pathlib import Path
import secrets
import sqlite3
import time


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@contextmanager
def database():
    directory = Path(os.environ.get('ORH_CLOUD_DATA', Path(__file__).resolve().parents[1] / '.runtime/cloud'))
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(directory / 'cloud.sqlite3', timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize():
    with database() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, salt TEXT NOT NULL,
          password_hash TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (
          digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS devices (
          instance_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          credential_hash TEXT UNIQUE NOT NULL, name TEXT NOT NULL, display_name TEXT,
          os TEXT NOT NULL, agent_addresses TEXT NOT NULL, manual_addresses TEXT NOT NULL DEFAULT '[]',
          excluded_addresses TEXT NOT NULL DEFAULT '[]', preferred TEXT, port INTEGER NOT NULL,
          last_seen REAL NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS bindings (
          code_hash TEXT UNIQUE, credential_hash TEXT PRIMARY KEY, instance_id TEXT NOT NULL,
          metadata TEXT NOT NULL, expires REAL NOT NULL, owner_id TEXT REFERENCES users(id), status TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tickets (
          digest TEXT PRIMARY KEY, instance_id TEXT NOT NULL REFERENCES devices(instance_id) ON DELETE CASCADE,
          session_digest TEXT NOT NULL REFERENCES sessions(digest) ON DELETE CASCADE,
          expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts (key TEXT NOT NULL, at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS attempts_key_time ON attempts(key,at);
        ''')


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()


def new_session(db, user_id):
    token = secrets.token_urlsafe(32)
    expires = time.time() + 7 * 86400
    db.execute('INSERT INTO sessions VALUES (?,?,?)', (digest(token), user_id, expires))
    return dict(token=token, expires=expires)
