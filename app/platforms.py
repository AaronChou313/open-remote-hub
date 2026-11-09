"""Host adapters. Common metrics stay portable; service discovery is platform-specific."""
import platform
import subprocess
import psutil


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

    def services(self):
        raise NotImplementedError


class MacHost(Host):
    def services(self):
        rows = command(['launchctl', 'list']).splitlines()[1:]
        return [dict(pid=None if a == '-' else int(a), exit=b, name=c, source='launchd', managed=False) for a,b,c in (x.split(None,2) for x in rows) if not c.startswith(('com.apple.', 'application.'))]


class LinuxHost(Host):
    def services(self):
        import json
        return [dict(name=x['unit'], status=x['active'], source='systemd', managed=False) for x in json.loads(command(['systemctl','--user','list-units','--type=service','--all','--output=json']))]


host = MacHost() if platform.system() == 'Darwin' else LinuxHost()


def process_detail(pid):
    if not isinstance(pid,int) or pid<=0:return None
    try:
        p=psutil.Process(pid)
        return dict(pid=pid,command=p.cmdline(),created=p.create_time(),status=p.status())
    except (psutil.Error,TypeError):return None


def service_detail(name):
    """Read only already-discovered user services, never arbitrary file paths."""
    from pathlib import Path
    import plistlib
    found=next((x for x in host.services() if x['name']==name),None)
    if not found:raise RuntimeError('Service not found')
    result={**found,'process':process_detail(found.get('pid')),'logs':{}}
    if platform.system()=='Darwin':
        for folder in (Path.home()/'Library/LaunchAgents',Path('/Library/LaunchAgents')):
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
        result['note']='未发现可读取的用户 LaunchAgent plist / 文件日志；不会读取任意文件或修改系统服务。'
    else:
        result['logs']['journal']=command(['journalctl','--user','-u',name,'-n','150','--no-pager'])
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
