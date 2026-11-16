"""Client directory, device-scoped channels and independent native windows."""
from pathlib import Path
import json
import sys
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import access, client, cloud_agent, desktop_client, discovery
from app import launcher
from test_files import workspace

LOCAL = 'c0d3a66a-9529-4a00-b43b-1a9158ce9eb0'
REMOTE = 'a5402db9-881c-478e-b15a-4e00586a32f0'


def test_native_launcher_loads_user_configuration(tmp_path, monkeypatch):
    import importlib.util
    (tmp_path / '.env').write_text('ORH_PORT=9876\nORH_CLOUD_PROXY=http://127.0.0.1:7891\n')
    monkeypatch.setenv('ORH_APP_DIR', str(tmp_path))
    monkeypatch.delenv('ORH_CONFIG_FILE', raising=False)
    monkeypatch.setenv('ORH_PORT', '')
    monkeypatch.delenv('ORH_PORT')
    monkeypatch.setenv('ORH_CLOUD_PROXY', 'http://explicit-proxy:7890')
    spec = importlib.util.spec_from_file_location('configured_launcher', Path(launcher.__file__))
    configured = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(configured)
    assert configured.URL == 'http://127.0.0.1:9876/'
    assert configured.os.environ['ORH_CLOUD_PROXY'] == 'http://explicit-proxy:7890'


def test_native_start_uses_saved_account_ticket(tmp_path, monkeypatch):
    binding = dict(status='bound', instance_id=LOCAL, cloud_url='https://cloud.example', account_token='saved-account')
    (tmp_path / 'cloud-binding.json').write_text(json.dumps(binding))
    requests = []
    class Cloud:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **options):
            requests.append((url, options))
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'url':'http://127.0.0.1:8765/auth/cloud#ticket=one-use'})
    monkeypatch.setattr(cloud_agent, 'http_client', lambda timeout: Cloud())
    url = desktop_client.initial_url('http://127.0.0.1:8765/client', tmp_path / 'client-webview')
    assert url == 'http://127.0.0.1:8765/auth/cloud?client_entry=1#ticket=one-use'
    assert requests[0][0].endswith('/api/devices/' + LOCAL + '/ticket')
    assert requests[0][1]['headers']['Authorization'] == 'Bearer saved-account'
    binding['account_token'] = ''
    (tmp_path / 'cloud-binding.json').write_text(json.dumps(binding))
    assert desktop_client.initial_url('http://127.0.0.1:8765/client', tmp_path / 'client-webview').endswith('/client')
    assert len(requests) == 1


def test_client_logout_forgets_account_and_retains_device(workspace, monkeypatch):
    http = workspace[0]
    original = dict(status='bound', credential='device-credential', account_token='account-session', instance_id=LOCAL)
    saved = []
    monkeypatch.setattr(cloud_agent, 'binding', lambda: original)
    monkeypatch.setattr(cloud_agent, 'fingerprint', lambda: None)
    monkeypatch.setattr(cloud_agent, 'save', saved.append)
    assert http.post('/api/auth/client/logout', json={}).status_code == 200
    assert saved[0]['credential'] == original['credential'] and saved[0]['account_token'] == ''
    assert http.get('/api/me').status_code == 401


def test_new_native_service_is_not_immediately_restarted(monkeypatch):
    health = iter([False, True])
    monkeypatch.setattr(launcher, 'healthy', lambda: next(health))
    monkeypatch.setattr(launcher, 'setup_service', lambda: 'started')
    monkeypatch.setattr(launcher.subprocess, 'run', lambda *args, **kwargs: pytest.fail('New service must start once'))
    assert launcher.ensure_server() is None


def test_linux_upgrade_restarts_existing_user_service(monkeypatch):
    health = iter([False, True])
    calls = []
    monkeypatch.setattr(launcher, 'healthy', lambda: next(health))
    monkeypatch.setattr(launcher, 'setup_service', lambda: 'running')
    monkeypatch.setattr(launcher.sys, 'platform', 'linux')
    monkeypatch.setattr(launcher.subprocess, 'run', lambda argv, **kwargs: calls.append(argv))
    assert launcher.ensure_server() is None
    assert calls == [['systemctl', '--user', 'restart', 'openremotehub.service']]


def test_installer_gives_legacy_windows_config_its_default_file_root(tmp_path, monkeypatch):
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    (bundle / 'VERSION').write_text('0.6.2')
    app = tmp_path / 'installed'
    app.mkdir()
    env = app / '.env'
    env.write_text('ORH_PORT=8765\nORH_DSH_ENABLED=0\n')
    monkeypatch.setattr(launcher, 'BUNDLE', bundle)
    monkeypatch.setattr(launcher, 'APP', app)
    launcher.install_files()
    assert 'ORH_FILE_ROOTS=' + json.dumps([str(Path.home())], ensure_ascii=False) in env.read_text()
    env.write_text('ORH_FILE_ROOTS=[]\n')
    launcher.install_files()
    assert env.read_text() == 'ORH_FILE_ROOTS=[]\n'


def test_stop_covers_user_copy_and_packaged_mesh(tmp_path, monkeypatch):
    import psutil
    app, bundle = tmp_path / 'user-app', tmp_path / 'bundle'
    expected = [app / 'bin/orh-mesh.exe', bundle / 'bin/orh-mesh.exe']
    stopped = []
    class Process:
        def __init__(self, path):
            self.path = path
            self.info = {'exe': str(path)}
        def terminate(self):
            stopped.append(self.path)
    monkeypatch.setattr(launcher, 'APP', app)
    monkeypatch.setattr(launcher, 'BUNDLE', bundle)
    monkeypatch.setattr(launcher.sys, 'platform', 'win32')
    monkeypatch.setattr(launcher, 'kill', lambda name: None)
    monkeypatch.setattr(psutil, 'process_iter', lambda attrs: [Process(path) for path in expected + [tmp_path / 'other/orh-mesh.exe']])
    launcher.stop_children()
    assert stopped == expected


@pytest.fixture
def directory(monkeypatch, workspace):
    rows = [dict(instance_id=LOCAL, name='Mac', os='Darwin', online=True),
            dict(instance_id=REMOTE, name='Windows & Lab', os='Windows', online=True,
                 mesh=dict(ips=['100.64.0.32'], services=[8765, 21118]))]
    mesh = dict(state='Running', device=dict(addresses=['100.64.0.17']),
                peers=[dict(addresses=['100.64.0.32'], route='relay')])
    monkeypatch.setattr(discovery, 'identity', lambda: dict(instance_id=LOCAL, name='Mac'))
    monkeypatch.setattr(cloud_agent, 'directory', lambda strict=False: rows)
    monkeypatch.setattr(client.tailscale, 'status', lambda: mesh)
    return workspace[0], rows, mesh


def test_directory_keeps_device_id_and_separates_heartbeat_from_path(directory):
    http, rows, mesh = directory
    # The unbound local fixture retains its local device without Cloud access.
    result = client.device_model(rows[1], mesh, LOCAL)
    assert result['device_id'] == REMOTE and result['path'] == 'relay'
    mesh['peers'][0]['route'] = 'idle'
    result = client.device_model(rows[1], mesh, LOCAL)
    assert result['heartbeat_online'] and result['path'] == 'idle'
    rows[1]['mesh']['ips'] = ['100.64.0.99']
    assert client.device_model(rows[1], mesh, LOCAL)['device_id'] == REMOTE
    assert http.get('/client').status_code == 200
    assert http.get('/api/client/devices').json()['devices'][0]['device_id'] == LOCAL


def test_cloud_failure_retains_local_device(directory, monkeypatch):
    http, rows, mesh = directory
    def unavailable(strict=False):
        raise HTTPException(503, 'Cloud 不可达')
    # Directory auth stays under the already authenticated local session.
    monkeypatch.setattr(cloud_agent, 'directory', unavailable)
    monkeypatch.setattr(cloud_agent, 'binding', lambda: {'cloud_url':'https://cloud.example'})
    monkeypatch.setattr(cloud_agent, 'fingerprint', lambda: None)
    result = http.get('/api/client/devices').json()
    assert result['cloud']['error'] == 'Cloud 不可达'
    assert len(result['devices']) == 1 and result['devices'][0]['local']


def test_connect_resolves_id_and_preserves_ticket_and_workspace_context(directory, monkeypatch):
    http, rows, mesh = directory
    calls = []
    def request(path, body, timeout):
        calls.append((path, body))
        return {'url':f'http://orh-{REMOTE}.localhost:12345/auth/cloud/enter'}
    monkeypatch.setattr(client.tailscale, 'request', request)
    monkeypatch.setattr(cloud_agent, 'ticket', lambda device, address, strict=False: address + '/auth/cloud#ticket=fixture-ticket&state=')
    result = http.post('/api/client/connect', json={'device_id':REMOTE, 'peer_ip':'192.0.2.1'})
    assert result.status_code == 200, result.text
    value = result.json()
    assert value['device_id'] == REMOTE and value['path'] == 'relay'
    assert calls == [('/console', {'peer_ip':'100.64.0.32', 'device_id':REMOTE})]
    url = urlsplit(value['url'])
    assert url.hostname == f'orh-{REMOTE}.localhost'
    assert parse_qs(url.query)['device_name'] == ['Windows & Lab']
    assert parse_qs(url.query)['peer_ip'] == ['100.64.0.17']
    assert parse_qs(url.query)['client'][0].endswith('/client')
    assert parse_qs(url.fragment)['ticket'] == ['fixture-ticket']


def test_connect_distinguishes_missing_device_mesh_agent_and_account(directory, monkeypatch):
    http, rows, mesh = directory
    assert http.post('/api/client/connect', json={'device_id':'unknown'}).status_code == 404
    mesh['state'] = 'NeedsLogin'
    result = http.post('/api/client/connect', json={'device_id':REMOTE})
    assert result.status_code == 503 and 'Mesh' in result.json()['detail']
    mesh['state'] = 'Running'
    rows[1]['mesh']['services'] = []
    result = http.post('/api/client/connect', json={'device_id':REMOTE})
    assert result.status_code == 409 and 'Agent' in result.json()['detail']
    rows[1]['mesh']['services'] = [8765]
    monkeypatch.setattr(client, 'console_connection', lambda value, require_ticket=False: {'url':'http://orh-device.localhost:12345/auth/cloud/enter'})
    result = http.post('/api/client/connect', json={'device_id':REMOTE})
    assert result.status_code == 401 and '登录' in result.json()['detail']


def test_local_workspace_and_link_do_not_need_cloud(directory):
    http, rows, mesh = directory
    result = http.post('/api/client/connect', json={'device_id':LOCAL})
    assert result.status_code == 200 and result.json()['path'] == 'local'
    assert parse_qs(urlsplit(result.json()['url']).query)['device_id'] == [LOCAL]
    assert http.get('/api/client/link?peer_ip=100.64.0.32').json()['path'] == 'relay'
    http.cookies.clear()
    assert http.get('/api/client/devices').status_code == 401
    assert http.post('/api/client/connect', json={'device_id':LOCAL}).status_code == 401


def test_client_login_refresh_preserves_binding_and_existing_agent_session(workspace, monkeypatch):
    http, _, _ = workspace
    original = dict(status='bound', cloud_url='https://cloud.example', owner_id='owner',
                    credential='device-credential', instance_id=LOCAL, username='aaron')
    cloud_agent.save(original)
    access.create('existing-agent-session', 'admin', time.time() + 300)
    monkeypatch.setattr(cloud_agent, 'call', lambda *args: {'user':{'id':'owner'}, 'token':'new-session', 'expires':time.time() + 300})
    response = http.post('/api/auth/client/login', json={'cloud_url':'https://cloud.example', 'username':'aaron', 'password':'test'})
    assert response.status_code == 200, response.text
    assert access.get('existing-agent-session')
    assert http.get('/api/me').status_code == 200
    assert all(cloud_agent.binding()[key] == value for key, value in original.items())
    monkeypatch.setattr(cloud_agent, 'call', lambda *args: {'user':{'id':'other-owner'}, 'token':'other', 'expires':time.time() + 300})
    assert http.post('/api/auth/client/login', json={'cloud_url':'https://cloud.example', 'username':'other', 'password':'test'}).status_code == 403
    assert cloud_agent.binding()['account_token'] == 'new-session'


def test_native_window_and_terminal_have_no_agent_stop_lifecycle(tmp_path, monkeypatch):
    windows, starts, scripts, closed = [], [], [], []
    class State:
        def __iadd__(self, handler):
            self.handler = handler
            return self
    def create_window(title, url, **options):
        window = SimpleNamespace(title=title, url=url, options=options, destroy=lambda: closed.append(title),
                                 load_url=lambda url: None, run_js=lambda script: scripts.append(script),
                                 state=State(), events=SimpleNamespace(closed=State()))
        window.get_current_url = lambda: window.url
        windows.append(window)
        return window
    webview = SimpleNamespace(windows=windows, settings={}, create_window=create_window, start=lambda **options: starts.append(options))
    menu = SimpleNamespace(Menu=lambda *args: args, MenuAction=lambda *args: args)
    monkeypatch.setitem(sys.modules, 'webview', webview)
    monkeypatch.setitem(sys.modules, 'webview.menu', menu)
    desktop_client.run('http://127.0.0.1:8765/client', tmp_path / 'webview')
    assert starts[0]['private_mode'] is False
    assert webview.settings['ALLOW_DOWNLOADS'] is True
    starts[0]['menu'][0][1][0][1]()
    assert 'returnToDevices()' in scripts[0] and 'eval(' not in scripts[0]
    assert windows[0].url.endswith('/client')
    assert 'js_api' not in windows[0].options
    state = windows[0].state
    windows[0].url = f'http://orh-{REMOTE}.localhost:12345/?client=local'
    state.handler('change', 'terminal_request', {'url':f'http://orh-{REMOTE}.localhost:12345/terminal/open/demo'})
    assert len(windows) == 2
    state.handler('change', 'terminal_request', {'url':'https://cloud.example/terminal/open/demo'})
    assert '网关' in state.terminal_error and len(windows) == 2
    state.handler('change', 'terminal_request', {'url':'http://127.0.0.1:8765/api/docker'})
    assert len(windows) == 2
    state.handler('change', 'terminal_request', {'url':'http://127.0.0.1:8765/terminal/open/demo'})
    assert '当前设备' in state.terminal_error and len(windows) == 2
    windows[0].events.closed.handler()
    assert closed == ['OpenRemoteHub · 终端']
    desktop_client.run('http://192.168.31.50:8765/client', tmp_path / 'lan-webview')
    windows[2].state.handler('change', 'terminal_request', {'url':'http://192.168.31.50:8765/terminal/open/demo'})
    assert len(windows) == 4


def test_windows_client_exit_keeps_server_and_startup_keeps_window_closed(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location('orh_launcher', Path(__file__).resolve().parents[1] / 'app/launcher.py')
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    calls = []
    monkeypatch.setattr(launcher, 'APP', tmp_path)
    monkeypatch.setattr(launcher, 'single_instance', lambda name='Tray': False)
    monkeypatch.setattr(launcher, 'install_files', lambda: None)
    monkeypatch.setattr(launcher, 'ensure_server', lambda: calls.append('ensure'))
    monkeypatch.setattr(launcher, 'stop_children', lambda: calls.append('stop'))
    monkeypatch.setattr(desktop_client, 'run', lambda *args: calls.append('window'))
    monkeypatch.setattr(sys, 'path', list(sys.path))
    launcher.client()
    assert calls == ['ensure', 'window']
    assert not (tmp_path / '.runtime/client.pid').exists()
    monkeypatch.setattr(sys, 'argv', ['OpenRemoteHub.exe', '--tray'])
    monkeypatch.setattr(launcher, 'tray', lambda open_window=True: calls.append(open_window))
    launcher.main()
    assert calls[-1] is False


def test_mac_bundle_keeps_background_process_out_of_dock():
    spec=(Path(__file__).resolve().parents[1]/'desktop/orh.spec').read_text()
    assert "'LSUIElement':True" in spec
