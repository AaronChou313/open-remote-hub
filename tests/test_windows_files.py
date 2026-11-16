import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main, windows_files


def test_windows_native_file_roundtrip(tmp_path, monkeypatch):
    root = tmp_path / 'files'
    root.mkdir()
    monkeypatch.setenv('ORH_FILE_ROOTS', json.dumps([str(root)]))
    monkeypatch.setattr(main, 'DATA', tmp_path)
    app = FastAPI()
    app.include_router(windows_files.router)
    with TestClient(app) as client:
        key = client.get('/api/files/roots').json()['roots'][0]['id']
        query = {'root': key, 'path': 'example.txt'}
        response = client.post('/api/files/upload', params=query, content=b'first')
        assert response.status_code == 200
        revision = response.json()['revision']
        assert client.post('/api/files/upload', params=query, content=b'collision').status_code == 409
        edited = client.post('/api/files/text', json={**query, 'revision': revision, 'text': 'updated', 'confirm': 'example.txt'})
        assert edited.status_code == 200
        assert client.get('/api/files/download', params=query, headers={'Range': 'bytes=0-2'}).content == b'upd'
        body = {**query, 'revision': edited.json()['revision'], 'action': 'delete', 'confirm': 'example.txt'}
        assert client.post('/api/files/operation', json=body).status_code == 200
        entry = client.get('/api/files/trash', params={'root': key}).json()['entries'][0]
        assert client.post('/api/files/restore', json={'root': key, 'name': entry['name'], 'revision': entry['revision'], 'confirm': 'example.txt'}).status_code == 200
        assert (root / 'example.txt').read_text() == 'updated'
        for invalid in ('../escape', 'CON.txt', 'folder/name:stream', 'trailing.'):
            assert client.post('/api/files/upload', params={'root': key, 'path': invalid}, content=b'x').status_code in (400, 403)
