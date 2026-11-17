from pathlib import Path
from types import SimpleNamespace

from app import modules, platforms, programs
from app.remote_connect.rustdesk import client


def test_docker_per_user_install_is_resolved_for_detection_and_commands(tmp_path, monkeypatch):
    folder = tmp_path / 'DockerDesktop'
    desktop = folder / 'Docker Desktop.exe'
    docker = folder / 'resources/bin/docker.exe'
    docker.parent.mkdir(parents=True)
    desktop.touch()
    docker.touch()
    monkeypatch.setattr(programs.sys, 'platform', 'win32')
    monkeypatch.setattr(programs, 'windows_install_directory', lambda name: folder)
    monkeypatch.setattr(programs.shutil, 'which', lambda name: None)
    assert programs.find('docker') == str(docker)
    calls = []
    def execute(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout='29.9.3', stderr='')
    monkeypatch.setattr(modules.subprocess, 'run', execute)
    assert modules.dependency('docker')['available']
    assert platforms.command(['docker', 'ps']) == '29.9.3'
    assert all(argv[0] == str(docker) for argv in calls)
    monkeypatch.setattr(modules.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout='', stderr='engine unavailable'))
    status = modules.dependency('docker')
    assert status['installed'] and status['can_open'] and not status['available']
    assert '已安装' in status['detail']


def test_windows_rustdesk_uses_official_cli_and_detects_exe_processes(tmp_path, monkeypatch):
    binary = tmp_path / 'rustdesk.exe'
    binary.touch()
    monkeypatch.setattr(client.sys, 'platform', 'win32')
    monkeypatch.setattr(client, 'binary', lambda: binary)
    process = SimpleNamespace(info={'name':'rustdesk.exe'}, pid=42, exe=lambda:str(binary),
                              cmdline=lambda:[str(binary), '--tray'], create_time=lambda:1)
    monkeypatch.setattr(client.psutil, 'process_iter', lambda fields:[process])
    monkeypatch.setattr(client, 'autostart', lambda:False)
    monkeypatch.setattr(client.subprocess, 'CREATE_NO_WINDOW', 0, raising=False)
    calls = []
    def query(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout='502852432\n')
    monkeypatch.setattr(client.subprocess, 'run', query)
    from contextlib import nullcontext
    monkeypatch.setattr(client.socket, 'create_connection', lambda *args, **kwargs:nullcontext())
    monkeypatch.setenv('APPDATA', str(tmp_path))
    def forbidden(*args):
        raise AssertionError('Windows must use its supported CLI, not Unix IPC')
    monkeypatch.setattr(client.native, 'config', forbidden)
    status = client.status()
    assert status['installed'] and status['ready'] and status['accepting']
    assert status['processes'][0]['pid'] == 42
    assert status['device_id'] == '502852432' and status['online'] is None
    assert not status['native_settings']
    assert calls == [[str(binary), '--get-id']]
    assert client.start() == {'reused':True}


def test_windows_nodebaby_has_supported_http_adapter_and_other_modules_explain_limits(monkeypatch):
    monkeypatch.setattr(modules.platform, 'system', lambda:'Windows')
    monkeypatch.setattr(modules, 'dependency', lambda name:dict(available=True, detail='Local API ready'))
    assert modules.status('nodebaby', {'nodebaby':True})['supported']
    for identifier, detail in [('knowledge','POSIX'), ('ssh','PTY'), ('proxy','TUN')]:
        status = modules.status(identifier, {identifier:True})
        assert not status['supported'] and detail in status['dependency']['detail']
