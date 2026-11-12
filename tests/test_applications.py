import pytest
from test_files import workspace
from app import applications


def test_application_crud_and_concurrent_edit(workspace):
    client,_,_ = workspace
    body = dict(name='开发服务',mode='host',scheme='http',port=3000,path='/ui?q=1',group='开发')
    response = client.post('/api/applications',json=body)
    assert response.status_code == 200
    saved = response.json()
    assert client.get('/api/applications').json()['applications'] == [saved]
    updated = client.post('/api/applications/'+saved['id'],json={**body,'name':'新名称','revision':saved['revision']})
    assert updated.status_code == 200
    assert client.post('/api/applications/'+saved['id'],json={**body,'revision':saved['revision']}).status_code == 409
    assert client.post('/api/applications/'+saved['id']+'/remove',json={'revision':saved['revision']}).status_code == 409
    assert client.post('/api/applications/'+saved['id']+'/remove',json={'revision':updated.json()['revision']}).status_code == 200
    assert client.get('/api/applications').json()['applications'] == []
    client.post('/api/logout',json={})
    assert client.get('/api/applications').status_code == 401
    assert client.post('/api/applications',json=body).status_code == 401
    assert client.get('/api/local-services').status_code == 401


@pytest.mark.parametrize('data',[
    dict(mode='host',port=0),dict(mode='host',port=65536),dict(mode='host',port=3000,path='//other.test'),
    dict(mode='host',port=3000,path='/\\other.test'),dict(mode='host',port=3000,path='/\n'),
    dict(mode='custom',url='javascript:alert(1)'),dict(mode='custom',url='file:///etc/passwd'),
    dict(mode='custom',url='http://localhost:99999'),dict(mode='custom',url='https://'),dict(mode='unknown'),
])
def test_application_invalid_addresses(data):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):applications.values(applications.Application(name='test',**data))


def test_custom_address_and_name_order(workspace):
    client,_,_ = workspace
    for name,url in [('zeta','https://example.org/path?q=1#section'),('Alpha','http://[::1]:3000/')]:
        assert client.post('/api/applications',json=dict(name=name,mode='custom',url=url)).status_code == 200
    assert [row['name'] for row in client.get('/api/applications').json()['applications']] == ['Alpha','zeta']
