"""Host adapters. Common metrics stay portable; service discovery is platform-specific."""
import platform
import subprocess
import psutil
import json
import re


def command(args, timeout=15, cwd=None):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=cwd, env={**{k:v for k,v in __import__('os').environ.items() if not k.startswith('ORH_')}, 'TERM':'xterm-256color'})
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(str(e)) from e
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout).strip()[:1500])
    return p.stdout


class Host:
    def info(self):
        return dict(hostname=platform.node(), system=platform.system(), version=platform.mac_ver()[0] or platform.release(), arch=platform.machine(), cores=psutil.cpu_count(), boot=psutil.boot_time())

    def services(self, scope='user'):
        raise NotImplementedError

    def listeners(self):
        result = []
        for connection in psutil.net_connections(kind='tcp'):
            if connection.status == psutil.CONN_LISTEN:
                result.append(dict(pid=connection.pid, address=connection.laddr.ip, port=connection.laddr.port))
        return result

    def proxy_status(self):
        return dict(platform='Linux',proxies=[],vpn=None,note='Linux 系统代理由桌面环境或服务配置管理')


class MacHost(Host):
    def proxy_status(self):
        import re
        values=command(['/usr/sbin/scutil','--proxy'],timeout=4)
        def value(key):
            match=re.search(r'^\s*'+key+r'\s*:\s*(.+)$',values,re.M)
            return match[1].strip() if match else None
        proxies=[dict(name=name,enabled=value(prefix+'Enable')=='1',server=value(prefix+'Proxy'),port=value(prefix+'Port')) for name,prefix in [('HTTP','HTTP'),('HTTPS','HTTPS'),('SOCKS','SOCKS')]]
        vpn=None
        for line in command(['/usr/sbin/scutil','--nc','list'],timeout=4).splitlines():
            if '[VPN:com.hako.network]' not in line:continue
            match=re.search(r'\(([^)]+)\).*?"([^"]+)"',line)
            if match:vpn=dict(state=match[1],name=match[2])
        return dict(platform='macOS',proxies=proxies,vpn=vpn)

    def services(self, scope='user'):
        if scope == 'user':
            rows = command(['launchctl', 'list']).splitlines()[1:]
            return [dict(pid=None if a == '-' else int(a), exit=b, name=c, source='launchd', scope=scope, managed=False)
                    for a,b,c in (x.split(None,2) for x in rows)]
        result = []
        block = False
        for line in command(['launchctl', 'print', 'system'], timeout=5).splitlines():
            if line == '\tservices = {':
                block = True
                continue
            if block and line == '\t}':
                break
            if block:
                parts = line.split(None, 2)
                if len(parts) == 3 and parts[0].isdigit():
                    result.append(dict(pid=int(parts[0]) or None, exit=parts[1], name=parts[2],
                                       source='launchd', scope=scope, managed=False))
        return result

    def listeners(self):
        return parse_mac_listeners(command(['/usr/sbin/netstat', '-anv', '-p', 'tcp'], timeout=5))


class LinuxHost(Host):
    def services(self, scope='user'):
        options = ['--user'] if scope == 'user' else []
        units = json.loads(command(['systemctl', *options, 'list-units', '--type=service', '--all', '--output=json']))
        names = [unit['unit'] for unit in units]
        if not names:
            return []
        details = command(['systemctl', *options, 'show', '--property=Id,MainPID,ActiveState,SubState,Description', '--', *names])
        result = []
        for block in details.strip().split('\n\n'):
            values = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
            if values.get('Id'):
                result.append(dict(name=values['Id'], pid=int(values.get('MainPID') or 0) or None,
                                   status=values.get('ActiveState'), description=values.get('Description'),
                                   source='systemd', scope=scope, managed=False))
        return result


def parse_mac_listeners(output):
    rows = []
    columns = []
    for line in output.splitlines():
        if line.startswith('Proto '):
            columns = line.replace('Local Address', 'Local_Address').replace('Foreign Address', 'Foreign_Address').split()
        values = line.split()
        if not values or not values[0].startswith('tcp') or 'LISTEN' not in values:
            continue
        address, port = values[3].rsplit('.', 1)
        if not port.isdecimal():
            continue
        name, pid = '', None
        if 'process:pid' in columns:
            # The process field may contain spaces, so identify its PID delimiter.
            match = re.search(r'([^\s:]+):(\d+)\s+[0-9a-fA-F]{4,}\s', line)
            if match:
                name, pid = match[1], int(match[2]) or None
        elif 'pid' in columns and len(values) > columns.index('pid'):
            pid = int(values[columns.index('pid')]) or None
        rows.append(dict(pid=pid, name=name, address=address.strip('[]'), port=int(port)))
    return rows


host = MacHost() if platform.system() == 'Darwin' else LinuxHost()


def process_detail(pid):
    if not isinstance(pid,int) or pid<=0:return None
    try:
        p=psutil.Process(pid)
        return dict(pid=pid,command=p.cmdline(),created=p.create_time(),status=p.status())
    except (psutil.Error,TypeError):return None


def service_detail(name, scope='user'):
    """Read an already-discovered service and its configured logs."""
    from pathlib import Path
    import plistlib
    found=next((x for x in host.services(scope) if x['name']==name and x.get('scope','user')==scope),None)
    if not found:raise RuntimeError('Service not found')
    result={**found,'process':process_detail(found.get('pid')),'logs':{}}
    if platform.system()=='Darwin':
        folders = (Path('/Library/LaunchDaemons'), Path('/System/Library/LaunchDaemons')) if scope=='system' else (Path.home()/'Library/LaunchAgents',Path('/Library/LaunchAgents'),Path('/System/Library/LaunchAgents'))
        for folder in folders:
            for path in folder.glob('*.plist'):
                try:
                    with path.open('rb') as f:cfg=plistlib.load(f)
                    if cfg.get('Label')!=name:continue
                    result['command']=cfg.get('ProgramArguments') or [cfg.get('Program')]
                    for key in ('StandardOutPath','StandardErrorPath'):
                        if not cfg.get(key):continue
                        log=Path(cfg[key]).expanduser()
                        try:
                            with log.open('rb') as f:
                                f.seek(max(0,log.stat().st_size-65536))
                                result['logs'][str(log)]=f.read(65536).decode(errors='replace')
                        except OSError as e:result['logs'][str(log)]=str(e)
                    return result
                except (OSError,plistlib.InvalidFileException):continue
        result['note']='此服务没有可读取的 plist 文件日志。'
    else:
        result['logs']['journal']=command(['journalctl',*(['--user'] if scope=='user' else []),'-u',name,'-n','150','--no-pager'])
    return result


def software_inventory():
    """Query installed packages only; never update Homebrew/APT indexes."""
    import shutil
    from app.workspace_commands import run
    if platform.system()=='Darwin':
        binary=shutil.which('brew')
        return dict(manager='Homebrew',available=bool(binary),**(run([binary,'list','--versions'],timeout=15) if binary else {'output':'未发现 Homebrew','truncated':False}))
    binary=shutil.which('dpkg-query')
    return dict(manager='APT / dpkg',available=bool(binary),**(run([binary,'-W','-f=${binary:Package}\t${Version}\n'],timeout=10) if binary else {'output':'此平台未发现 dpkg-query；未执行安装','truncated':False}))
