from test_files import workspace
from pathlib import Path
import subprocess
from app import workspace_store as store


def test_project_registry_git_and_safe_removal(workspace):
    c,key,root=workspace
    folder=root/'demo';folder.mkdir()
    subprocess.run(['git','init','-q',str(folder)],check=True)
    (folder/'package.json').write_text('{"scripts":{"test":"node -e \\\"console.log(1)\\\""}}')
    (folder/'note.txt').write_text('before')
    (folder/'.env').write_text('DO_NOT_SHOW_SECRET=before')
    subprocess.run(['git','-C',str(folder),'add','.'],check=True)
    subprocess.run(['git','-C',str(folder),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','Initial'],check=True)
    (folder/'note.txt').write_text('after');(folder/'.env').write_text('DO_NOT_SHOW_SECRET=after')
    p=c.post('/api/projects',json=dict(root=key,path='demo',name='Demo')).json()
    assert 'id' in p
    assert c.post('/api/projects',json=dict(root=key,path='demo',name='Duplicate')).status_code==409
    detail=c.get('/api/projects/'+p['id']).json()
    assert detail['git'] and 'Node.js' in detail['stack']
    assert detail['presets'][0]['key']=='test'
    for kind in ('status','branches','commits','diff','staged'):
        r=c.get('/api/projects/'+p['id']+'/git',params={'kind':kind});assert r.status_code==200,r.text
        assert 'DO_NOT_SHOW_SECRET' not in r.text
    assert 'after' in c.get('/api/projects/'+p['id']+'/git?kind=diff').json()['output']
    assert c.post('/api/projects/'+p['id'],json=dict(action='remove',revision=p['revision'])).status_code==400
    assert c.post('/api/projects/'+p['id'],json=dict(action='remove',revision=p['revision'],confirm=p['id'])).status_code==200
    assert (folder/'note.txt').exists()
    assert not store.rows('project')


def test_project_paths_unavailable_and_task_confirmation(workspace):
    c,key,root=workspace
    assert c.post('/api/projects',json=dict(root=key,path='../private',name='No')).status_code==403
    (root/'demo').mkdir();(root/'demo'/'package.json').write_text('{"scripts":{"dev":"echo safe"}}')
    p=c.post('/api/projects',json=dict(root=key,path='demo',name='Demo')).json()
    assert c.post('/api/projects/'+p['id'],json=dict(action='run',revision=p['revision'],preset='dev')).status_code==400
    assert c.post('/api/projects/'+p['id'],json=dict(action='run',revision=p['revision'],preset='dev',confirm=p['id'],digest='stale')).status_code==409
    (root/'demo').rename(root/'moved')
    assert not c.get('/api/projects').json()['projects'][0]['available']
    assert c.get('/api/projects/'+p['id']).status_code==404
    assert c.post('/api/projects/'+p['id'],json=dict(action='remove',revision=p['revision'],confirm=p['id'])).status_code==200


def test_repository_cannot_redirect_worktree_or_run_fsmonitor(workspace):
    c,key,root=workspace
    folder=root/'repo';folder.mkdir()
    subprocess.run(['git','init','-q',str(folder)],check=True)
    marker=root/'unwanted-hook'
    subprocess.run(['git','-C',str(folder),'config','core.fsmonitor','touch '+str(marker)],check=True)
    p=c.post('/api/projects',json=dict(root=key,path='repo',name='Repo')).json()
    assert c.get('/api/projects/'+p['id']+'/git?kind=status').status_code==200
    assert not marker.exists()
    outside=root/'other';outside.mkdir()
    subprocess.run(['git','-C',str(folder),'config','core.worktree',str(outside)],check=True)
    assert c.get('/api/projects/'+p['id']+'/git?kind=diff').status_code==403
    assert c.get('/api/projects/'+p['id']+'/git?kind=status%3Btouch').status_code in (400,403)


def test_discover_projects_and_removal_does_not_reappear(workspace,monkeypatch):
    c,key,root=workspace
    folder=root/'Projects';folder.mkdir()
    (folder/'demo').mkdir();(folder/'other').mkdir();(folder/'.hidden').mkdir();(folder/'alias').symlink_to(folder/'demo')
    monkeypatch.setenv('ORH_PROJECTS_DIR',str(folder))
    rows=c.get('/api/projects').json()['projects']
    assert {p['name'] for p in rows}=={'demo','other'}
    assert all(p['discovered'] for p in rows)
    assert len(c.get('/api/projects').json()['projects'])==2
    p=rows[0]
    assert c.post('/api/projects/'+p['id'],json=dict(action='remove',revision=p['revision'],confirm=p['id'])).status_code==200
    assert len(c.get('/api/projects').json()['projects'])==1
    assert (folder/p['name']).is_dir()
