"""Real Markdown files in temporary roots, using the console auth entry points."""
from test_files import workspace


def add(client, directory, **values):
    response = client.post('/api/knowledge', json=dict(directory=str(directory), **values))
    assert response.status_code == 200, response.text
    return response.json()


def test_library_create_edit_persist_remove_and_unavailable(workspace):
    client, _, root = workspace
    row = add(client, root / 'research' / 'notes', name='研究', create=True)
    assert (root / 'research' / 'notes').is_dir()
    assert client.post('/api/knowledge', json=dict(directory=str(root / 'research' / 'notes'))).status_code == 409
    changed = client.post('/api/knowledge/' + row['id'], json=dict(name='机器人', revision=row['revision']))
    assert changed.status_code == 200
    assert client.post('/api/knowledge/' + row['id'], json=dict(name='stale', revision=row['revision'])).status_code == 409
    assert client.get('/api/knowledge').json()['libraries'][0]['name'] == '机器人'
    (root / 'research' / 'notes').rename(root / 'research' / 'moved')
    assert not client.get('/api/knowledge').json()['libraries'][0]['available']
    assert client.post('/api/knowledge/' + row['id'], json=dict(action='remove', revision=changed.json()['revision'])).status_code == 200
    assert (root / 'research' / 'moved').is_dir()
    assert not client.get('/api/knowledge').json()['libraries']


def test_notes_create_read_edit_conflict_rename_delete_restore(workspace):
    client, key, root = workspace
    row = add(client, root, name='笔记')
    base = '/api/knowledge/' + row['id']
    assert client.post(base + '/note', json=dict(path='定位/研究.md', text='# 研究\n\n中文 **Markdown**')).status_code == 200
    assert client.post(base + '/note', json=dict(path='定位/研究.md', text='overwrite')).status_code == 409
    (root / 'data.txt').write_text('not a note')
    tree = client.get(base + '/tree').json()
    assert tree['count'] == 1
    assert [entry['path'] for entry in tree['entries']] == ['定位', '定位/研究.md']
    note = client.get(base + '/note', params=dict(path='定位/研究.md')).json()
    assert '中文' in note['text']
    edit = dict(path=note['path'], text='# 新内容', revision=note['revision'])
    saved = client.post(base + '/note', json=edit)
    assert saved.status_code == 200
    assert client.post(base + '/note', json=edit).status_code == 409
    renamed = client.post(base + '/operation', json=dict(action='rename', path=note['path'], destination='定位/新版.markdown', revision=saved.json()['revision']))
    assert renamed.status_code == 200
    read = client.get(base + '/note', params=dict(path='定位/新版.markdown')).json()
    assert read['text'] == '# 新内容'
    op = dict(action='delete', path=read['path'], revision=read['entry_revision'])
    assert client.post(base + '/operation', json=op).status_code == 400
    assert client.post(base + '/operation', json=dict(op, confirm=read['path'])).status_code == 200
    trash = client.get('/api/files/trash', params=dict(root=key, path='定位')).json()['entries'][0]
    assert client.post('/api/files/restore', json=dict(root=key, path='定位', name=trash['name'], revision=trash['revision'], confirm=trash['original_name'])).status_code == 200
    assert (root / '定位' / '新版.markdown').read_text() == '# 新内容'
    assert (root / 'data.txt').exists()


def test_library_rebind_and_directory_trash_are_explicit(workspace):
    client, key, root = workspace
    row = add(client, root / 'first', create=True)
    (root / 'second').mkdir()
    moved = client.post('/api/knowledge/' + row['id'], json=dict(directory=str(root / 'second'), revision=row['revision']))
    assert moved.status_code == 200
    (root / 'second' / 'hello.md').write_text('hello')
    body = dict(action='trash', revision=moved.json()['revision'])
    assert client.post('/api/knowledge/' + row['id'], json=body).status_code == 400
    assert client.post('/api/knowledge/' + row['id'], json=dict(body, confirm=row['id'])).status_code == 200
    assert (root / 'first').is_dir()
    assert not (root / 'second').exists()
    trash = client.get('/api/files/trash', params=dict(root=key)).json()['entries']
    assert any(entry['original_name'] == 'second' for entry in trash)


def test_scope_extensions_symlinks_and_utf8_limit(workspace, monkeypatch):
    client, _, root = workspace
    assert client.post('/api/knowledge', json=dict(directory=str(root.parent))).status_code == 403
    assert client.post('/api/knowledge', json=dict(directory=str(root / '..' / 'outside'))).status_code == 403
    row = add(client, root)
    base = '/api/knowledge/' + row['id']
    for path in ('../escape.md', '/absolute.md', 'a/../../escape.md', 'file.txt', 'x\\note.md'):
        assert client.post(base + '/note', json=dict(path=path)).status_code in (400, 403)
        assert client.get(base + '/note', params=dict(path=path)).status_code in (400, 403)
    assert client.post(base + '/note', json=dict(path='large.md', text='中' * 400000)).status_code == 413
    (root / 'outside.md').symlink_to(root.parent / 'outside.md')
    (root.parent / 'outside.md').write_text('outside')
    assert client.get(base + '/note', params=dict(path='outside.md')).status_code in (403, 409)
    monkeypatch.setenv('ORH_FILE_POLICY', 'unrestricted')
    (root / 'loop').symlink_to(root, target_is_directory=True)
    assert client.get(base + '/tree').status_code == 200
    assert client.get(base + '/asset', params=dict(path='../outside.md')).status_code == 403


def test_auth_and_asset_download(workspace):
    client, _, root = workspace
    row = add(client, root)
    (root / 'diagram.png').write_bytes(b'png-fixture')
    response = client.get('/api/knowledge/' + row['id'] + '/asset', params=dict(path='diagram.png'))
    assert response.status_code == 200 and response.headers['content-type'] == 'image/png'
    client.post('/api/logout', json={})
    assert client.get('/api/knowledge').status_code == 401
    assert client.post('/api/knowledge', json=dict(directory=str(root))).status_code == 401
