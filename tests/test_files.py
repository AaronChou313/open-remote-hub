import json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import pytest
from fastapi.testclient import TestClient
from app import main,passwords,file_access as fs

@pytest.fixture
def workspace(tmp_path,monkeypatch):
    data=tmp_path/'private';data.mkdir();root=tmp_path/'files';root.mkdir()
    monkeypatch.setattr(main,'DATA',data)
    monkeypatch.setenv('ORH_FILE_ROOTS',json.dumps([str(root)]))
    # macOS pytest temporary fixtures live under /private; actual system writes remain blocked.
    monkeypatch.setattr(fs,'SYSTEM',tuple(x for x in fs.SYSTEM if x!='/private'))
    main.attempts.clear();passwords.save('files-test-password',initial=True)
    c=TestClient(main.app,base_url=f'http://127.0.0.1:{main.PORT}',headers={'X-ORH-Request':'1'})
    assert c.post('/api/login',json={'password':'files-test-password'}).status_code==200
    return c,fs.roots()[0]['id'],root


def test_files_real_operations_conflicts_and_download(workspace):
    c,key,root=workspace
    def upload(name,data=b'hello'):return c.post('/api/files/upload',params={'root':key,'path':name},content=data)
    assert upload('one.txt').status_code==200
    assert upload('one.txt',b'overwrite').status_code==409
    r=c.get('/api/files/text',params={'root':key,'path':'one.txt'}).json()
    edit=dict(root=key,path='one.txt',text='中文',revision=r['revision'],confirm='one.txt')
    assert c.post('/api/files/text',json=edit).status_code==200
    assert c.post('/api/files/text',json=edit).status_code==409
    assert (root/'one.txt').read_text()=='中文'
    assert c.get('/api/files/download',params={'root':key,'path':'one.txt'},headers={'Range':'bytes=0-2'}).content=='中'.encode()
    for action,destination in [('copy','two.txt'),('rename','renamed.txt'),('delete','')]:
        row=c.get('/api/files/text',params={'root':key,'path':'one.txt' if action=='copy' else 'two.txt' if action=='rename' else 'renamed.txt'}).json()
        path='one.txt' if action=='copy' else 'two.txt' if action=='rename' else 'renamed.txt'
        body=dict(root=key,path=path,action=action,destination=destination,revision=row['revision'],confirm=path)
        assert c.post('/api/files/operation',json=body).status_code==200
    assert not (root/'renamed.txt').exists()
    assert (root/'.remotehub-trash').is_dir()
    trashed=c.get('/api/files/trash',params={'root':key}).json()['entries'][0]
    restore=dict(root=key,path='',name=trashed['name'],revision=trashed['revision'],confirm=trashed['original_name'])
    (root/'renamed.txt').write_text('new content')
    assert c.post('/api/files/restore',json=restore).status_code==409
    assert (root/'renamed.txt').read_text()=='new content'
    (root/'renamed.txt').unlink()
    assert c.post('/api/files/restore',json=restore).status_code==200
    assert (root/'renamed.txt').read_text()=='中文'
    assert not (root/'.remotehub-trash').exists()
    assert c.get('/api/files/search',params={'root':key,'q':'one'}).json()['entries'][0]['name']=='one.txt'


def test_file_boundaries_and_links(workspace,tmp_path):
    c,key,root=workspace
    (root/'.env').write_text('secret');(root/'auth.json').write_text('secret')
    (root/'link').symlink_to(tmp_path)
    (root/'folder').mkdir();(root/'folder'/'escape').symlink_to(tmp_path)
    for path in ('../private','/etc/passwd','folder/../.env','.env','auth.json','link/private','folder/escape/private','a\\b'):
        assert c.get('/api/files/text',params={'root':key,'path':path}).status_code in (403,404)
    (root/'normal').write_text('data');os.link(root/'normal',root/'hardlink')
    assert c.get('/api/files/download',params={'root':key,'path':'hardlink'}).status_code==403
    assert c.post('/api/files/upload',params={'root':key,'path':'link/unsafe'},content=b'no').status_code==403
    row=next(x for x in c.get('/api/files/list',params={'root':key}).json()['entries'] if x['name']=='folder')
    assert c.post('/api/files/operation',json=dict(root=key,path='folder',action='copy',destination='copy',revision=row['revision'])).status_code==403
    assert not (root/'copy').exists()
    assert c.post('/api/files/operation',json=dict(root=key,path='',action='delete',confirm='')).status_code==403


def test_directory_copy_and_no_replace(workspace):
    c,key,root=workspace
    (root/'a').mkdir();(root/'a'/'nested').mkdir();(root/'a'/'nested'/'hello.txt').write_text('hi')
    row=c.get('/api/files/list',params={'root':key}).json()['entries'][0]
    body=dict(root=key,path='a',action='copy',destination='b',revision=row['revision'])
    assert c.post('/api/files/operation',json=body).status_code==200
    assert (root/'b'/'nested'/'hello.txt').read_text()=='hi'
    assert c.post('/api/files/operation',json=body).status_code==409
    assert c.post('/api/files/operation',json={**body,'action':'move','destination':'b','confirm':'a'}).status_code==409
    assert (root/'a').exists()


def test_upload_limits_and_auth(workspace,monkeypatch):
    c,key,root=workspace;monkeypatch.setenv('ORH_MAX_UPLOAD_MB','1')
    assert c.post('/api/files/upload',params={'root':key,'path':'big'},content=b'x'*(1024**2+1)).status_code==413
    assert not (root/'big').exists()
    assert not list(root.glob('.orh-*'))
    c.post('/api/logout',json={})
    assert c.get('/api/files/list',params={'root':key}).status_code==401
    assert c.post('/api/files/upload',params={'root':key,'path':'unauthorized'},content=b'x').status_code==401


def test_symlink_parent_swaps_and_sensitive_subtrees(workspace):
    c,key,root=workspace
    (root/'a').mkdir();(root/'a'/'f').write_text('old')
    (root/'a').rename(root/'renamed');(root/'a').symlink_to(root/'renamed',target_is_directory=True)
    assert c.get('/api/files/text',params={'root':key,'path':'a/f'}).status_code==403
    assert (root/'renamed'/'f').read_text()=='old'


def test_external_edit_conflict_and_simultaneous_upload(workspace):
    from concurrent.futures import ThreadPoolExecutor
    c,key,root=workspace
    (root/'edit.txt').write_text('original')
    old=c.get('/api/files/text',params={'root':key,'path':'edit.txt'}).json()
    (root/'edit.txt').write_text('external edit')
    assert c.post('/api/files/text',json=dict(root=key,path='edit.txt',text='overwrite',revision=old['revision'],confirm='edit.txt')).status_code==409
    assert (root/'edit.txt').read_text()=='external edit'
    with ThreadPoolExecutor(2) as pool:
        statuses=list(pool.map(lambda data:c.post('/api/files/upload',params={'root':key,'path':'race.txt'},content=data).status_code,[b'first',b'second']))
    assert sorted(statuses)==[200,409]
    assert (root/'race.txt').read_bytes() in (b'first',b'second')
    assert not list(root.glob('.orh-*'))


def test_whole_directory_cannot_bypass_absolute_protection(workspace,monkeypatch):
    c,key,root=workspace
    folder=root/'container';folder.mkdir();(folder/'vault').mkdir();(folder/'vault'/'secret').write_text('never copied')
    original=fs.sensitive_absolute
    monkeypatch.setattr(fs,'sensitive_absolute',lambda p:original(p) or p==folder/'vault' or folder/'vault' in p.parents)
    row=c.get('/api/files/list',params={'root':key}).json()['entries'][0]
    assert c.post('/api/files/operation',json=dict(root=key,path='container',action='copy',destination='copied',revision=row['revision'])).status_code==403
    assert not (root/'copied').exists()


def test_streaming_ranges_and_text_size_limits(workspace):
    c,key,root=workspace
    with (root/'large.bin').open('wb') as f:f.truncate(16*1024*1024)
    assert c.get('/api/files/text',params={'root':key,'path':'large.bin'}).status_code==413
    r=c.get('/api/files/download',params={'root':key,'path':'large.bin'},headers={'Range':'bytes=-32'})
    assert r.status_code==206 and len(r.content)==32 and r.headers['content-range'].startswith('bytes ')
    assert c.get('/api/files/download',params={'root':key,'path':'large.bin'},headers={'Range':'bytes=99999999-'}).status_code==416


@pytest.mark.live
def test_real_directory_terminal_create_and_existing_cwd_preserved(workspace):
    import secrets
    from app.zellij_manage import mutate
    from app.zellij_sessions import host_sessions
    c,key,root=workspace;(root/'other').mkdir()
    name='orh-file-'+secrets.token_hex(3)
    baseline={s['name']:(s.get('pid'),s.get('created')) for s in host_sessions()}
    try:
        r=c.post('/api/files/terminal',json=dict(root=key,path='',session=name))
        assert r.status_code==200,r.text
        assert r.json()['cwd_applied']
        layout=main.cli(['zellij','--session',name,'action','dump-layout'],3)
        assert 'cwd "'+str(root.resolve())+'"' in layout
        r=c.post('/api/files/terminal',json=dict(root=key,path='other',session=name))
        assert r.status_code==200 and not r.json()['cwd_applied']
        assert 'cwd "'+str(root.resolve())+'"' in main.cli(['zellij','--session',name,'action','dump-layout'],3)
    finally:
        if any(s['name']==name for s in host_sessions()):mutate(name,'purge')
    assert baseline=={s['name']:(s.get('pid'),s.get('created')) for s in host_sessions()}


def test_host_root_does_not_enable_system_writes(workspace,monkeypatch):
    c,key,root=workspace
    monkeypatch.setenv('ORH_FILE_ROOTS','["/"]')
    host=fs.roots()[0]['id']
    assert c.get('/api/files/list',params={'root':host}).status_code==200
    assert c.post('/api/files/operation',json=dict(root=host,path='usr/orh-must-not-be-created',action='mkdir')).status_code==403
    assert c.get('/api/files/text',params={'root':host,'path':'Users/aaron/.ssh/id_ed25519'}).status_code==403


def test_sort_hidden_filter_and_home_default(workspace,monkeypatch):
    c,key,root=workspace
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:root))
    (root/'.hidden').mkdir();(root/'folder').mkdir()
    (root/'z.txt').write_text('zzz');(root/'a.txt').write_text('a')
    assert c.get('/api/files/roots').json()['default']=={'root':key,'path':''}
    query={'root':key,'show_hidden':'false','sort':'size','order':'desc'}
    result=c.get('/api/files/list',params=query).json()
    assert [r['name'] for r in result['entries']]==['folder','z.txt','a.txt']
    assert '.hidden' in [r['name'] for r in c.get('/api/files/list',params={**query,'show_hidden':'true'}).json()['entries']]
    assert not c.get('/api/files/search',params={'root':key,'q':'hidden','show_hidden':'false'}).json()['entries']
    assert c.get('/api/files/list',params={**query,'sort':'invalid'}).status_code==400
    (root/'node_modules').mkdir()
    assert c.get('/api/files/list',params={'root':key,'path':'node_modules'}).status_code==200
