from test_files import workspace
import json,os
import pytest
from app import environments as envs


def test_passive_venv_metadata_binding_and_no_execution(workspace,monkeypatch):
    c,key,root=workspace
    folder=root/'demo';folder.mkdir();venv=folder/'.venv';venv.mkdir()
    (venv/'pyvenv.cfg').write_text('version = 3.14.7\n')
    packages=venv/'lib/python3.14/site-packages/example-1.0.dist-info';packages.mkdir(parents=True)
    (packages/'METADATA').write_text('Name: example\nVersion: 1.0\n\nDescription')
    (venv/'bin').mkdir();(venv/'bin/python').write_text('#!/bin/sh\ntouch SHOULD_NEVER_RUN\n')
    p=c.post('/api/projects',json=dict(root=key,path='demo',name='Demo')).json()
    monkeypatch.setattr(envs,'installed_tools',lambda:[])
    monkeypatch.setattr(envs.shutil,'which',lambda name:None)
    listing=c.get('/api/environments').json()
    e=next(x for x in listing['environments'] if x['kind']=='venv')
    assert e['version']=='3.14.7'
    assert c.get('/api/environments/'+e['id']).json()['packages']==[{'name':'example','version':'1.0'}]
    assert not (folder/'SHOULD_NEVER_RUN').exists()
    bound=c.post('/api/projects/'+p['id'],json=dict(action='environment',revision=p['revision'],environment=e['id'])).json()
    assert bound['environment']['id']==e['id']
    assert c.post('/api/projects/'+p['id'],json=dict(action='environment',revision=p['revision'],environment=e['id'])).status_code==409
    assert c.post('/api/projects/'+p['id'],json=dict(action='environment',revision=bound['revision'],environment='')).status_code==400
    assert c.post('/api/projects/'+p['id'],json=dict(action='environment',revision=bound['revision'],environment='',confirm=p['id'])).status_code==200


def test_create_plan_confirmation_and_existing_environment(workspace,monkeypatch):
    c,key,root=workspace;(root/'demo').mkdir()
    p=c.post('/api/projects',json=dict(root=key,path='demo',name='Demo')).json()
    body={'project':p['id']}
    plan=c.post('/api/environments/plan',json=body).json()
    assert 'digest' in plan
    assert c.post('/api/environments/create',json=body).status_code==400
    assert c.post('/api/environments/create',json={**body,'digest':'stale','confirm':p['id']}).status_code==400
    assert not (root/'demo/.venv').exists()
    calls=[]
    def run(argv,**kwargs):calls.append((argv,kwargs));return {'output':'','truncated':False}
    monkeypatch.setattr(envs,'run',run)
    assert c.post('/api/environments/create',json={**body,'digest':plan['digest'],'confirm':p['id']}).status_code==200
    assert calls and calls[0][0][-2:]==['venv','.'] and 'cwd_fd' in calls[0][1]
    assert c.post('/api/environments/create',json={**body,'digest':plan['digest'],'confirm':p['id']}).status_code==409
    assert c.post('/api/environments/plan',json={**body,'name':'../bad'}).status_code==400


@pytest.mark.live
def test_real_venv_creation_in_own_fixture(workspace):
    c,key,root=workspace;(root/'own-project').mkdir()
    p=c.post('/api/projects',json=dict(root=key,path='own-project',name='Own venv test')).json()
    plan=c.post('/api/environments/plan',json={'project':p['id']}).json()
    r=c.post('/api/environments/create',json={'project':p['id'],'digest':plan['digest'],'confirm':p['id']})
    assert r.status_code==200,r.text
    assert (root/'own-project/.venv/pyvenv.cfg').is_file()
    assert c.get('/api/projects/'+p['id']).json()['environment'] is None
