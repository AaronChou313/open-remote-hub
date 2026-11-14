"""Database contexts release handles without waiting for garbage collection."""
from pathlib import Path
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from app import main, workspace_store
from app.ssh import storage


@pytest.mark.parametrize('factory',[main.db,workspace_store.connection,storage.connect])
def test_connections_close_and_transactions_commit_or_rollback(factory,tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    monkeypatch.setattr(main,'DB',tmp_path/'metrics.sqlite3')
    with factory() as connection:
        connection.execute('CREATE TABLE probe(value INTEGER)')
        connection.execute('INSERT INTO probe VALUES (1)')
    with pytest.raises(sqlite3.ProgrammingError,match='closed'):
        connection.execute('SELECT 1')
    with pytest.raises(RuntimeError,match='rollback'):
        with factory() as failed:
            failed.execute('INSERT INTO probe VALUES (2)')
            raise RuntimeError('rollback')
    with pytest.raises(sqlite3.ProgrammingError,match='closed'):
        failed.execute('SELECT 1')
    with factory() as check:
        assert check.execute('SELECT value FROM probe').fetchall()==[(1,)]
