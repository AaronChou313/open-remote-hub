from pathlib import Path
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import orn_runtime


@pytest.fixture(autouse=True)
def clean_state(monkeypatch, tmp_path):
    monkeypatch.setattr(orn_runtime, 'log_path', lambda: tmp_path / 'orn.log')
    monkeypatch.setattr(orn_runtime, 'pid_path', lambda: tmp_path / 'orn.pid')
    monkeypatch.setattr(orn_runtime, 'RESTARTS', 0)
    monkeypatch.setattr(orn_runtime, 'ERROR', '')
    monkeypatch.setattr(orn_runtime, 'NOTE', '')
    monkeypatch.setattr(orn_runtime, 'TAKEOVER', False)
    monkeypatch.setattr(orn_runtime, 'SERVICE_CACHE', (0.0, None))
    monkeypatch.setattr(orn_runtime, 'standalone_service', lambda: None)
    yield


def fake_binary(tmp_path):
    path = tmp_path / ('orn-agent.exe' if sys.platform == 'win32' else 'orn-agent')
    path.write_text('#!/bin/sh\nexit 0\n')
    path.chmod(0o755)
    return path


def isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(orn_runtime, 'ROOT', tmp_path / 'orh')
    monkeypatch.setattr(orn_runtime.shutil, 'which', lambda name: None)


def test_binary_is_optional(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    monkeypatch.setenv('ORH_ORN_BIN', str(tmp_path / 'missing'))
    assert orn_runtime.binary() is None
    monkeypatch.delenv('ORH_ORN_ENABLED', raising=False)
    assert orn_runtime.enabled() is False


def test_binary_and_config_from_environment(monkeypatch, tmp_path):
    binary = fake_binary(tmp_path)
    monkeypatch.setenv('ORH_ORN_BIN', str(binary))
    monkeypatch.setenv('ORH_ORN_CONFIG', str(tmp_path / 'orn' / 'config.json'))
    assert orn_runtime.binary() == binary
    assert orn_runtime.enabled() is True
    assert orn_runtime.ensure_config() is True
    path = tmp_path / 'orn' / 'config.json'
    value = json.loads(path.read_text())
    assert value['api_addr'] == '127.0.0.1:4789'
    assert value['publish']['21118'] == '127.0.0.1:21118'
    assert value['publish']['8765'].startswith('127.0.0.1:')
    assert oct(path.stat().st_mode & 0o777) == '0o600'
    assert orn_runtime.token_path() == tmp_path / 'orn' / 'api.token'
    assert orn_runtime.ensure_config() is False


def test_disabled_switch(monkeypatch, tmp_path):
    monkeypatch.setenv('ORH_ORN_BIN', str(fake_binary(tmp_path)))
    monkeypatch.setenv('ORH_ORN_ENABLED', 'off')
    assert orn_runtime.enabled() is False


def test_probe_requires_token(monkeypatch, tmp_path):
    monkeypatch.setenv('ORH_ORN_CONFIG', str(tmp_path / 'config.json'))
    assert orn_runtime.token() == ''
    assert orn_runtime.probe() is False


def test_status_reports_missing_runtime(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    monkeypatch.setenv('ORH_ORN_BIN', str(tmp_path / 'missing'))
    monkeypatch.setenv('ORH_ORN_CONFIG', str(tmp_path / 'config.json'))
    value = orn_runtime.status()
    assert value['available'] is False and value['running'] is False
    assert value['config'].endswith('config.json')


def test_takeover_stops_standalone_before_spawning(monkeypatch, tmp_path):
    monkeypatch.setenv('ORH_ORN_BIN', str(fake_binary(tmp_path)))
    calls = []
    monkeypatch.setattr(orn_runtime, 'disable_standalone', lambda: calls.append('disable') or '已停止独立服务')
    monkeypatch.setattr(orn_runtime, 'probe', lambda timeout=2: False)
    monkeypatch.setattr(orn_runtime, '_spawn', lambda: calls.append('spawn') or None)
    value = orn_runtime.takeover()
    assert calls == ['disable', 'spawn']
    assert value['takeover'] is True and value['note'] == '已停止独立服务'
    assert value['managed'] is False
    assert orn_runtime.stop() is False


def test_save_config_validates_and_restarts(monkeypatch, tmp_path):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps(dict(control_url='https://hs.example', hostname='old',
                                      state_dir=str(tmp_path / 'state'), api_addr='127.0.0.1:4789',
                                      cloud={'device_id': 'keep-me'}, publish={'21118': '127.0.0.1:21118'})))
    monkeypatch.setattr(orn_runtime, 'config_path', lambda: config)
    restarted = []
    monkeypatch.setattr(orn_runtime, 'restart', lambda: restarted.append(True))
    monkeypatch.setattr(orn_runtime, 'status', lambda: dict(running=True))
    value = orn_runtime.save_config(dict(hostname='new-host', control_url='https://hs.openremotehub.top',
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
            orn_runtime.save_config(bad)


def test_restart_prefers_owned_process(monkeypatch):
    calls = []
    monkeypatch.setattr(orn_runtime, 'managed', lambda: True)
    monkeypatch.setattr(orn_runtime, 'stop', lambda: calls.append('stop') or True)
    monkeypatch.setattr(orn_runtime, 'start', lambda: calls.append('start'))
    monkeypatch.setattr(orn_runtime, 'probe', lambda timeout=2: False)
    monkeypatch.setattr(orn_runtime, 'status', lambda: dict(running=True))
    orn_runtime.restart()
    assert calls == ['stop', 'start']
