"""Portable inventory fixtures plus a real loopback HTTP listener."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest
import psutil
from fastapi import HTTPException
from app import local_services as services, platforms, main


@pytest.fixture
def inventory(monkeypatch):
    monkeypatch.setattr(platforms.host, 'services', lambda scope: [])
    monkeypatch.setattr(platforms.host, 'listeners', lambda: [])
    monkeypatch.setattr(services, 'docker_services', lambda: [])
    monkeypatch.setattr(main, 'tasks_list', lambda: [])
    monkeypatch.setattr(services, 'process', lambda pid: dict(name='python', created=100, command=['python','app.py']) if pid else None)
    services.probe_cache.clear()


def test_mac_listener_parser_root_ipv6_and_old_pid_column():
    current = '''Active Internet connections
Proto Recv-Q Send-Q Local Address Foreign Address (state) rxbytes txbytes rhiwat shiwat process:pid state options
 tcp4 0 0 127.0.0.1.8765 *.* LISTEN 0 0 131072 131072 Python:111 00100 00000000
 tcp6 0 0 ::1.443 *.* LISTEN 0 0 131072 131072 root-service:222 00100 00000000
 tcp4 0 0 192.168.1.2.5000 192.168.1.3.1234 ESTABLISHED 0 0 131072 131072 Python:111 00100 00000000
'''
    rows = platforms.parse_mac_listeners(current)
    assert rows == [dict(pid=111,name='Python',address='127.0.0.1',port=8765),dict(pid=222,name='root-service',address='::1',port=443)]
    old = 'Proto Recv-Q Send-Q Local Address Foreign Address (state) rxbytes txbytes rhiwat shiwat pid epid\ntcp4 0 0 *.80 *.* LISTEN 0 0 1 1 123 123'
    assert platforms.parse_mac_listeners(old)[0] == dict(pid=123,name='',address='*',port=80)


def test_mac_managers_include_apple_and_system(monkeypatch):
    def command(argv, **kwargs):
        if argv == ['launchctl','list']:
            return 'PID Status Label\n123 0 com.apple.example\n- 0 custom.idle'
        assert argv == ['launchctl','print','system']
        return 'system = {\n\tservices = {\n\t\t 456 - custom.root\n\t\t 0 - com.apple.idle\n\t}\n\tother = {\n\t\t 789 - ignored\n\t}\n}'
    monkeypatch.setattr(platforms,'command',command)
    adapter = platforms.MacHost()
    assert adapter.services()[0]['name'] == 'com.apple.example'
    assert adapter.services()[1]['pid'] is None
    assert [(row['name'],row['pid']) for row in adapter.services('system')] == [('custom.root',456),('com.apple.idle',None)]


def test_linux_manager_scopes(monkeypatch):
    calls = []
    def command(argv, **kwargs):
        calls.append(argv)
        if 'list-units' in argv:
            return '[{"unit":"web.service"},{"unit":"idle.service"}]'
        return 'Id=web.service\nMainPID=42\nActiveState=active\nDescription=Web\n\nId=idle.service\nMainPID=0\nActiveState=inactive\n'
    monkeypatch.setattr(platforms,'command',command)
    adapter = platforms.LinuxHost()
    assert adapter.services()[0]['pid'] == 42
    assert '--user' in calls[0] and '--user' in calls[1]
    assert adapter.services('system')[1]['pid'] is None
    assert all('--user' not in call for call in calls[2:])
    assert calls[1][-3:] == ['--','web.service','idle.service']


def test_inventory_association_dedup_and_probe_cache(inventory,monkeypatch):
    monkeypatch.setattr(platforms.host,'services',lambda scope:[dict(name='com.apple.web',pid=123,source='launchd',scope=scope)] if scope=='system' else [])
    listeners = [dict(pid=123,address='127.0.0.1',port=3210)]*2 + [dict(pid=456,address='0.0.0.0',port=4321)]
    monkeypatch.setattr(platforms.host,'listeners',lambda:listeners)
    probes = []
    def probe(item):
        probes.append(item['port'])
        return dict(protocol='http',http_status=200)
    monkeypatch.setattr(services,'identify_web',probe)
    rows = services.inventory()['services']
    assert len(rows) == 2
    apple = next(row for row in rows if row['apple'])
    assert apple['scope'] == 'system' and len(apple['endpoints']) == 1
    assert apple['endpoints'][0]['binding'] == 'loopback'
    assert sorted(probes) == [3210,4321]
    services.inventory()
    assert len(probes) == 2
    services.inventory(force=True)
    assert len(probes) == 4
    assert services.inventory(probe=False)['services'][0]['endpoints'][0]['protocol'] == 'http'


def test_docker_port_association_and_unknown_pid_ids(inventory,monkeypatch):
    container = dict(id='docker-id',name='web',source='Docker',scope='container',running=True,created=100,pid=None,process=None,
                     endpoints=[services.endpoint(dict(address='0.0.0.0',port=6080,target='80/tcp'))])
    monkeypatch.setattr(services,'docker_services',lambda:[container])
    monkeypatch.setattr(platforms.host,'listeners',lambda:[dict(pid=2,address='*',port=6080),dict(pid=None,address='127.0.0.1',port=22),dict(pid=None,address='::1',port=22)])
    rows = services.inventory(probe=False)['services']
    assert len(rows) == 3
    assert len({row['id'] for row in rows}) == 3
    assert container['endpoints'][0]['pid'] == 2
    assert not any(row['pid']==2 for row in rows)


def test_partial_scope_failure_and_project_log_detail(inventory,monkeypatch):
    def manager(scope):
        if scope=='system':raise RuntimeError('not available')
        return [dict(name='user-unit',pid=12,source='systemd',scope=scope)]
    monkeypatch.setattr(platforms.host,'services',manager)
    monkeypatch.setattr(main,'tasks_list',lambda:[dict(id='project',name='npm dev',running=True,pid=30,created=100)])
    monkeypatch.setattr(main,'task_logs',lambda key:dict(output='real task output'))
    result = services.inventory(probe=False)
    assert len(result['services']) == 2 and len(result['warnings']) == 1
    assert services.detail('task-project')['details']['logs']['运行输出'] == 'real task output'
    with pytest.raises(HTTPException) as error:services.detail('gone')
    assert error.value.status_code == 404


def test_real_http_detection_and_unprivileged_process():
    class Handler(BaseHTTPRequestHandler):
        def do_HEAD(self):
            self.send_response(401)
            self.end_headers()
        def log_message(self,*args):pass
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        result = services.identify_web(dict(address='127.0.0.1',port=server.server_port))
        assert result['protocol'] == 'http' and result['http_status'] == 401
        process = services.process(psutil.Process().pid)
        assert process['pid'] == psutil.Process().pid and process['created'] > 0
    finally:
        server.shutdown();server.server_close();thread.join()
