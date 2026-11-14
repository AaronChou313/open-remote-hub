from pathlib import Path
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import mesh_runtime


@pytest.fixture(autouse=True)
def clean_state(monkeypatch, tmp_path):
    monkeypatch.setattr(mesh_runtime, 'log_path', lambda: tmp_path / 'orn.log')
    monkeypatch.setattr(mesh_runtime, 'pid_path', lambda: tmp_path / 'orn.pid')
    monkeypatch.setattr(mesh_runtime, 'RESTARTS', 0)
    monkeypatch.setattr(mesh_runtime, 'ERROR', '')
    monkeypatch.setattr(mesh_runtime, 'NOTE', '')
    monkeypatch.setattr(mesh_runtime, 'TAKEOVER', False)
    monkeypatch.setattr(mesh_runtime, 'SERVICE_CACHE', (0.0, None))
    monkeypatch.setattr(mesh_runtime, 'standalone_service', lambda: None)
    yield


def fake_binary(tmp_path):
    path = tmp_path / ('orh-mesh.exe' if sys.platform == 'win32' else 'orh-mesh')
    path.write_text('#!/bin/sh\nexit 0\n')
    path.chmod(0o755)
    return path


def isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(mesh_runtime, 'ROOT', tmp_path / 'orh')
    monkeypatch.setattr(mesh_runtime.shutil, 'which', lambda name: None)


def test_binary_is_optional(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    monkeypatch.setenv('ORH_MESH_BIN', str(tmp_path / 'missing'))
    assert mesh_runtime.binary() is None
    monkeypatch.delenv('ORH_MESH_ENABLED', raising=False)
    assert mesh_runtime.enabled() is False


def test_binary_and_config_from_environment(monkeypatch, tmp_path):
    binary = fake_binary(tmp_path)
    monkeypatch.setenv('ORH_MESH_BIN', str(binary))
    monkeypatch.setenv('ORH_MESH_CONFIG', str(tmp_path / 'orn' / 'config.json'))
    assert mesh_runtime.binary() == binary
    assert mesh_runtime.enabled() is True
    assert mesh_runtime.ensure_config() is True
    path = tmp_path / 'orn' / 'config.json'
    value = json.loads(path.read_text())
    assert value['api_addr'] == '127.0.0.1:4789'
    assert value['publish']['21118'] == '127.0.0.1:21118'
    assert value['publish']['8765'].startswith('127.0.0.1:')
    assert oct(path.stat().st_mode & 0o777) == '0o600'
    assert mesh_runtime.token_path() == tmp_path / 'orn' / 'api.token'
    assert mesh_runtime.ensure_config() is False


def test_disabled_switch(monkeypatch, tmp_path):
    monkeypatch.setenv('ORH_MESH_BIN', str(fake_binary(tmp_path)))
    monkeypatch.setenv('ORH_MESH_ENABLED', 'off')
    assert mesh_runtime.enabled() is False


def test_probe_requires_token(monkeypatch, tmp_path):
    monkeypatch.setenv('ORH_MESH_CONFIG', str(tmp_path / 'config.json'))
    assert mesh_runtime.token() == ''
    assert mesh_runtime.probe() is False


def test_status_reports_missing_runtime(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    monkeypatch.setenv('ORH_MESH_BIN', str(tmp_path / 'missing'))
    monkeypatch.setenv('ORH_MESH_CONFIG', str(tmp_path / 'config.json'))
    value = mesh_runtime.status()
    assert value['available'] is False and value['running'] is False
    assert value['config'].endswith('config.json')


def test_takeover_stops_standalone_before_spawning(monkeypatch, tmp_path):
    monkeypatch.setenv('ORH_MESH_BIN', str(fake_binary(tmp_path)))
    calls = []
    monkeypatch.setattr(mesh_runtime, 'disable_standalone', lambda: calls.append('disable') or '已停止独立服务')
    monkeypatch.setattr(mesh_runtime, 'probe', lambda timeout=2: False)
    monkeypatch.setattr(mesh_runtime, '_spawn', lambda: calls.append('spawn') or None)
    value = mesh_runtime.takeover()
    assert calls == ['disable', 'spawn']
    assert value['takeover'] is True and value['note'] == '已停止独立服务'
    assert value['managed'] is False
    assert mesh_runtime.stop() is False


def test_save_config_validates_and_restarts(monkeypatch, tmp_path):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps(dict(control_url='https://hs.example', hostname='old',
                                      state_dir=str(tmp_path / 'state'), api_addr='127.0.0.1:4789',
                                      cloud={'device_id': 'keep-me'}, publish={'21118': '127.0.0.1:21118'})))
    monkeypatch.setattr(mesh_runtime, 'config_path', lambda: config)
    restarted = []
    monkeypatch.setattr(mesh_runtime, 'restart', lambda: restarted.append(True))
    monkeypatch.setattr(mesh_runtime, 'status', lambda: dict(running=True))
    value = mesh_runtime.save_config(dict(hostname='new-host', control_url='https://hs.openremotehub.top',
                                         publish={'8765': '127.0.0.1:8765'}))
    assert value == dict(running=True) and restarted == [True]
    saved = json.loads(config.read_text())
    assert saved['hostname'] == 'new-host'
    assert saved['cloud'] == {'device_id': 'keep-me'}
    assert saved['publish'] == {'8765': '127.0.0.1:8765'}
    assert oct(config.stat().st_mode & 0o777) == '0o600'
    for bad in (dict(hostname='', control_url='https://hs.example', publish={}),
                dict(hostname='ok', control_url='http://public.example', publish={}),
                dict(hostname='ok', control_url='https://hs.example', publish={'8765': '10.0.0.5:8765'}),
                dict(hostname='ok', control_url='https://hs.example', publish={'70000': '127.0.0.1:8765'})):
        with pytest.raises(ValueError):
            mesh_runtime.save_config(bad)


def test_restart_prefers_owned_process(monkeypatch):
    calls = []
    monkeypatch.setattr(mesh_runtime, 'managed', lambda: True)
    monkeypatch.setattr(mesh_runtime, 'stop', lambda: calls.append('stop') or True)
    monkeypatch.setattr(mesh_runtime, 'start', lambda: calls.append('start'))
    monkeypatch.setattr(mesh_runtime, 'probe', lambda timeout=2: False)
    monkeypatch.setattr(mesh_runtime, 'status', lambda: dict(running=True))
    mesh_runtime.restart()
    assert calls == ['stop', 'start']
