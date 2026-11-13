"""Native snapshot filtering, bounded actions and service diagnostic behavior."""
import json
from pathlib import Path
import sys

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.remote_connect import nodebaby
from test_remote_connect import management
from test_files import workspace


@pytest.fixture
def native(monkeypatch):
    info = {'name': 'NodeBabyLinkService', 'version': '4.5.3', 'pid': 349,
            'peerid': 'private-self-id', 'tun': 'succ', 'host': {'hostname': 'Mac'},
            'private-field': 'must-stay-native'}
    routes = {'code': 0, 'states': [
        {'pid': 'private-self-id', 'map': '10.77.1.2', 'ipv4': '127.0.0.1', 'prefix': 32, 'domain': 'mac.link'},
        {'pid': 'remote-id', 'map': '10.77.1.3', 'ipv4': '127.0.0.1', 'prefix': 32, 'domain': 'windows.link'},
        {'pid': 'remote-id', 'map': '--shell', 'ipv4': '127.0.0.1', 'prefix': 32},
    ]}
    def request(path, transport=False):
        return {'/detect/version': info, '/tun/routers': routes, '/glp/sipstate': {'result': 0, 'state': 1},
                '/glp/peerlist': ['remote-id']}[path]
    monkeypatch.setattr(nodebaby, 'request', request)
    return info, routes


def test_native_status_and_secret_filtering(native):
    value = nodebaby.status()
    assert value['ready'] and value['connected'] and value['tun_ready']
    assert value['addresses'] == ['10.77.1.2']
    assert len(value['mappings']) == 2
    assert value['mappings'][0]['self']
    assert value['mappings'][1]['link_active']
    assert value['mappings'][0]['group'] == '10.77.1.0/24'
    assert 'private-self-id' not in json.dumps(value)
    assert 'must-stay-native' not in json.dumps(value)
    native[0]['tun'] = 'off'
    assert not nodebaby.status()['tun_ready']


def test_incompatible_and_missing_native(monkeypatch, native):
    native[0]['name'] = 'other-service'
    value = nodebaby.status()
    assert not value['ready'] and '其他服务' in value['error']
    def offline(*args, **kwargs):
        raise nodebaby.NodeBabyError('服务未启动')
    monkeypatch.setattr(nodebaby, 'request', offline)
    assert not nodebaby.status()['ready']
    assert nodebaby.status()['mappings'] == []


def test_probe_uses_only_current_mapping(native, monkeypatch):
    calls = []
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(nodebaby.socket, 'create_connection', lambda address, timeout: calls.append((address, timeout)) or Connection())
    result = nodebaby.probe('10.77.1.3/32', 22)
    assert result['reachable']
    assert calls == [(('10.77.1.3', 22), 3)]
    for target, port in [('127.0.0.1/32', 22), ('--shell', 22), ('10.77.1.3/32', 0), ('10.77.1.3/32', '22'), ('10.77.1.3/32', True)]:
        with pytest.raises(ValueError): nodebaby.probe(target, port)
    assert len(calls) == 1


@pytest.mark.parametrize('error, text', [(ConnectionRefusedError(), '拒绝'), (TimeoutError(), '超时'), (OSError(), '失败')])
def test_probe_failure_is_actionable(native, monkeypatch, error, text):
    def fail(*args, **kwargs): raise error
    monkeypatch.setattr(nodebaby.socket, 'create_connection', fail)
    result = nodebaby.probe('10.77.1.3/32', 22)
    assert not result['reachable'] and text in result['message']


def test_native_open_uses_fixed_argv(monkeypatch):
    calls = []
    monkeypatch.setattr(nodebaby.sys, 'platform', 'darwin')
    monkeypatch.setattr(nodebaby.Path, 'exists', lambda path: True)
    monkeypatch.setattr(nodebaby.subprocess, 'run', lambda argv, **kwargs: calls.append(argv))
    nodebaby.open_client()
    assert calls == [['/usr/bin/open', '-a', '/Applications/节点小宝.app']]


def test_authenticated_nodebaby_actions(management, monkeypatch):
    http, _, audit = management
    monkeypatch.setattr(nodebaby, 'open_client', lambda: None)
    monkeypatch.setattr(nodebaby, 'probe', lambda identifier, port: dict(reachable=True, address='10.77.1.2', port=port))
    assert http.get('/api/remote-connect').json()['nodebaby']['mappings'] == []
    assert http.post('/api/remote-connect/nodebaby/open', json={}).status_code == 200
    assert audit[-1] == ('nodebaby', 'open-client')
    assert http.post('/api/remote-connect/nodebaby/probe', json={'id':'10.77.1.2/32', 'port':8765}).json()['reachable']
    http.cookies.clear()
    assert http.post('/api/remote-connect/nodebaby/open', json={}).status_code == 401
