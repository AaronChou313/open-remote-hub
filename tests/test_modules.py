import json
from pathlib import Path
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main, modules
from test_files import workspace


def test_fresh_core_has_no_optional_requirements(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DATA', tmp_path)
    monkeypatch.setattr(modules, 'dependency', lambda value: {'available':False,'detail':'not installed'})
    assert not any(modules.load().values())
    assert all(value['state']=='disabled' for value in modules.listing()['modules'])
    with pytest.raises(HTTPException) as error:
        modules.require('docker')
    assert error.value.status_code == 409


def test_module_missing_dependency_recheck_and_disable_preserve_tasks(workspace, monkeypatch):
    http, _, _ = workspace
    modules.save({key:False for key in modules.CATALOG})
    monkeypatch.setattr(modules, 'dependency', lambda value: {'available':False,'detail':'Docker Engine unavailable'})
    assert http.get('/api/docker').status_code == 409
    enabled = http.post('/api/modules/docker/enable', json={}).json()
    assert enabled['state'] == 'missing_dependency' and enabled['enabled']
    monkeypatch.setattr(modules, 'dependency', lambda value: {'available':True,'detail':'installed'})
    assert http.get('/api/modules/docker').json()['state'] == 'ready'
    assert http.post('/api/modules/docker/disable', json={}).json()['state'] == 'disabled'
    assert http.get('/api/docker').status_code == 409
    assert json.loads(modules.state_path().read_text())['docker'] is False


def test_existing_installation_retains_module_choices(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DATA', tmp_path)
    (tmp_path/'credentials.json').write_text('{}')
    assert all(modules.load().values())
    modules.disable('docker')
    assert not modules.enabled('docker')
    assert modules.enabled('terminal')
