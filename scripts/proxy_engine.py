#!/usr/bin/env python3
"""Small local broker for a dedicated Mihomo. Standard library only, no shell.

Installed as a root-owned copy for TUN. The HTTP socket belongs to one OS user.
Never controls another proxy client. No host routing is changed during staging.
"""
import argparse
import copy
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import signal
import socketserver
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit

LIMIT = 4 * 1024 * 1024
EXCLUDES = ['127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '100.64.0.0/10']
LABEL = 'local.openremotehub.proxy'


def atomic(path, value):
    fd, name = tempfile.mkstemp(dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, ensure_ascii=False); f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def normalize(source, home, secret, enabled=False, mode=None):
    """Own listeners/routes; retain user rules, DNS and outbound configuration."""
    allowed = {'proxies', 'proxy-groups', 'proxy-providers', 'rules', 'rule-providers', 'dns', 'hosts',
               'sniffer', 'mode', 'log-level', 'ipv6', 'find-process-mode', 'unified-delay',
               'tcp-concurrent', 'global-client-fingerprint', 'global-ua', 'geodata-mode',
               'geodata-loader', 'geox-url', 'geo-auto-update', 'geo-update-interval',
               'keep-alive-interval', 'keep-alive-idle', 'disable-keep-alive'}
    if any(str(key).startswith('x-clash-') for key in source):
        raise ValueError('此配置是客户端内部格式，请导入机场提供的标准 Clash / Mihomo YAML')
    cfg = {k: copy.deepcopy(v) for k, v in source.items() if k in allowed}
    if not isinstance(cfg.get('proxies', []), list) or not isinstance(cfg.get('proxy-groups', []), list):
        raise ValueError('proxies 和 proxy-groups 必须为列表')
    for key in ('proxy-providers', 'rule-providers'):
        providers = cfg.get(key, {})
        if not isinstance(providers, dict): raise ValueError('Provider 格式无效')
        for name, row in providers.items():
            if not isinstance(row, dict) or row.get('type') not in ('http', 'inline'):
                raise ValueError('Provider 请使用 http 或 inline；本地文件请先合并进配置')
            if row.get('type') == 'http':
                parsed = urlsplit(str(row.get('url', '')))
                if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError('Provider URL 无效')
            row['path'] = str(home / 'providers' / (hashlib.sha256((key+name).encode()).hexdigest()+'.yaml'))
    cfg.update({'mixed-port':7891, 'port':0, 'socks-port':0, 'redir-port':0, 'tproxy-port':0,
                'allow-lan':False, 'bind-address':'127.0.0.1', 'external-controller':'127.0.0.1:19090',
                'secret':secret, 'profile':{'store-selected':True, 'store-fake-ip':True}})
    cfg['mode'] = mode or cfg.get('mode', 'rule')
    if cfg['mode'] not in ('rule', 'global', 'direct'): raise ValueError('模式无效')
    cfg.setdefault('log-level', 'info')
    rules = cfg.setdefault('rules', ['MATCH,DIRECT'])
    if not isinstance(rules, list) or not all(isinstance(x, str) for x in rules): raise ValueError('rules 必须为字符串列表')
    cfg['rules'] = ['IP-CIDR,'+x+',DIRECT,no-resolve' for x in EXCLUDES] + rules
    dns = cfg.setdefault('dns', {'enable':True, 'enhanced-mode':'fake-ip', 'nameserver':['https://dns.alidns.com/dns-query', 'https://1.1.1.1/dns-query'], 'default-nameserver':['223.5.5.5', '1.1.1.1']})
    if not isinstance(dns, dict): raise ValueError('DNS 配置无效')
    dns['enable'] = True
    dns['listen'] = '127.0.0.1:1054'
    cfg['tun'] = {'enable':enabled, 'stack':'mixed', 'auto-route':True, 'auto-detect-interface':True,
                  'dns-hijack':['any:53'], 'route-exclude-address':EXCLUDES, 'strict-route':False}
    return cfg


def clash_connected():
    if __import__('sys').platform != 'darwin': return False
    try:
        value = subprocess.run(['/usr/sbin/scutil', '--nc', 'list'], capture_output=True, text=True, timeout=4, check=True)
    except (OSError, subprocess.SubprocessError):
        raise ValueError('无法确认 Clash 连接状态，未启用新代理')
    return any('[VPN:com.hako.network]' in line and '(Disconnected)' not in line for line in value.stdout.splitlines())


class Engine:
    def __init__(self, home, binary):
        self.home, self.binary = home, binary
        self.lock = threading.RLock()
        home.mkdir(mode=0o700, parents=True, exist_ok=True)
        (home/'providers').mkdir(mode=0o700, exist_ok=True)
        self.secret_path = home/'secret.json'
        if not self.secret_path.exists(): atomic(self.secret_path, __import__('secrets').token_urlsafe(36))
        self.secret = json.loads(self.secret_path.read_text())
        self.state_path = home/'state.json'
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {'source':{}, 'enabled':False, 'mode':'rule'}
        # A second client may have been enabled while this service was down.
        if self.state['enabled'] and clash_connected(): self.state['enabled'] = False
        self.write_config()
        self.process = None
        self.launch()

    def core(self, method, path, data=None):
        connection = http.client.HTTPConnection('127.0.0.1', 19090, timeout=6)
        try:
            connection.request(method, path, body=json.dumps(data).encode() if data is not None else None,
                               headers={'Authorization':'Bearer '+self.secret, 'Content-Type':'application/json'})
            result = connection.getresponse(); raw = result.read(8*1024*1024+1)
            if len(raw)>8*1024*1024: raise ValueError('内核响应过大')
            if result.status>=400: raise ValueError('内核拒绝操作，HTTP '+str(result.status))
            return json.loads(raw) if raw else {}
        finally: connection.close()

    def config(self, source=None, enabled=None):
        return normalize(self.state['source'] if source is None else source, self.home, self.secret,
                         self.state['enabled'] if enabled is None else enabled, self.state.get('mode'))

    def write_config(self):
        atomic(self.home/'config.json', self.config())
        atomic(self.state_path, self.state)

    def launch(self):
        # Do not replace an unknown controller or kill any unrelated process.
        import socket
        with socket.socket() as s:
            if s.connect_ex(('127.0.0.1',19090))==0: raise ValueError('19090 已被占用，未连接未知服务')
        logfile=self.home/'engine.log'
        if logfile.exists() and logfile.stat().st_size>8*1024*1024: logfile.replace(self.home/'engine.previous.log')
        with logfile.open('ab') as log:
            self.process=subprocess.Popen([str(self.binary), '-d', str(self.home), '-f', str(self.home/'config.json')],
                                          stdout=log, stderr=log, stdin=subprocess.DEVNULL, env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin', 'HOME':str(self.home)})
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            if self.process.poll() is not None: raise ValueError('Mihomo 启动失败，请查看内核日志')
            try: self.core('GET','/version'); return
            except (OSError, ValueError): time.sleep(.1)
        self.stop()
        raise ValueError('Mihomo 启动超时')

    def status(self):
        return dict(ready=self.process.poll() is None, enabled=self.state['enabled'], privileged=os.geteuid()==0,
                    configured=bool(self.state['source'].get('proxies') or self.state['source'].get('proxy-providers')),
                    revision=digest(self.state), config_revision=digest(self.state['source']),
                    exclusions=EXCLUDES, mixed_port=7891, pid=self.process.pid)

    def validate(self, source):
        if not isinstance(source,dict): raise ValueError('配置格式无效')
        cfg=self.config(source=source,enabled=False)
        atomic(self.home/'candidate.json',cfg)
        try:
            result=subprocess.run([str(self.binary),'-t','-d',str(self.home),'-f',str(self.home/'candidate.json')],
                                  stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=35)
            if result.returncode: raise ValueError('Mihomo 配置检查失败，原配置保持不变。请检查 YAML、节点协议或规则依赖')
        finally: (self.home/'candidate.json').unlink(missing_ok=True)
        return {'ok':True}

    def change(self, body):
        if body.get('revision') != digest(self.state): raise ValueError('状态已变化，请刷新后重试')
        action=body.get('action')
        if action not in ('enable','disable','apply','restart'): raise ValueError('不支持的内核操作')
        old=copy.deepcopy(self.state)
        if action=='enable':
            if not self.status()['configured']: raise ValueError('请先导入并选择机场配置')
            if os.geteuid()!=0: raise ValueError('TUN 服务尚未安装，请在主机完成一次管理员安装')
            if clash_connected(): raise ValueError('Clash 仍在连接，请先手动关闭 Clash，再启动新代理')
            self.state['enabled']=True
        elif action=='disable':
            # Emergency stop must not wait on provider/geodata downloads or validation.
            self.state['enabled']=False
            self.write_config()
            try:
                self.core('PATCH','/configs',{'tun':{'enable':False}})
                actual=self.core('GET','/configs')
                if actual.get('tun',{}).get('enable'):raise ValueError('TUN 未关闭')
            except (OSError,ValueError):
                self.stop();self.launch()
            return self.status()
        elif action=='apply':
            if not isinstance(body.get('source'),dict): raise ValueError('配置格式无效')
            self.state['source']=body['source']
        if action=='restart' and self.state['enabled'] and clash_connected():self.state['enabled']=False
        mutated=False
        try:
            cfg=self.config()
            # Validate a disabled candidate. -t must never install TUN routes.
            check_cfg=self.config(enabled=False)
            atomic(self.home/'candidate.json',check_cfg)
            result=subprocess.run([str(self.binary),'-t','-d',str(self.home),'-f',str(self.home/'candidate.json')],
                                  stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=35)
            if result.returncode: raise ValueError('Mihomo 配置检查失败，原配置保持不变')
            if action=='restart':
                mutated=True
                self.stop(); self.write_config(); self.launch()
            else:
                mutated=True
                self.core('PUT','/configs?force=true',{'payload':json.dumps(cfg)})
            actual=self.core('GET','/configs')
            if bool(actual.get('tun',{}).get('enable')) != self.state['enabled']: raise ValueError('TUN 状态与目标不同')
            self.write_config()
        except Exception:
            self.state=old
            if mutated:
                try:
                    if self.process.poll() is not None: self.write_config(); self.launch()
                    else: self.core('PUT','/configs?force=true',{'payload':json.dumps(self.config())}); self.write_config()
                except Exception: pass
            raise
        finally:
            (self.home/'candidate.json').unlink(missing_ok=True)
        return self.status()

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=8)
            except subprocess.TimeoutExpired: self.process.kill(); self.process.wait()


class Server(socketserver.UnixStreamServer):
    allow_reuse_address=True
    last_retry=0

    def service_actions(self):
        if self.engine.process.poll() is None or time.monotonic()-self.last_retry<30:return
        self.last_retry=time.monotonic()
        try:
            if self.engine.state['enabled'] and clash_connected():self.engine.state['enabled']=False
            self.engine.write_config();self.engine.launch()
        except (ValueError,OSError,subprocess.SubprocessError):pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass  # subscription/config secrets never reach request logs

    def do_GET(self): self.handle_request()
    def do_POST(self): self.handle_request()
    def do_PUT(self): self.handle_request()
    def do_PATCH(self): self.handle_request()
    def do_DELETE(self): self.handle_request()

    def handle_request(self):
        status=200
        try:
            engine=self.server.engine
            size=int(self.headers.get('Content-Length','0'))
            if size<0 or size>LIMIT: raise ValueError('请求过大')
            body=json.loads(self.rfile.read(size)) if size else None
            with engine.lock:
                if self.path=='/orh/state' and self.command=='GET': result=engine.status()
                elif self.path=='/orh/control' and self.command=='POST': result=engine.change(body or {})
                elif self.path=='/orh/validate' and self.command=='POST': result=engine.validate((body or {}).get('source'))
                elif self.path=='/orh/logs' and self.command=='GET':
                    with (engine.home/'engine.log').open('rb') as f:
                        f.seek(max(0,os.fstat(f.fileno()).st_size-32768)); value=f.read().decode(errors='replace')
                    # Do not publish URLs (may include subscription tokens) or UUIDs.
                    value=re.sub(r'https?://[^\s"\x1b]+','[URL]',value)
                    value=re.sub(r'\b[\da-fA-F]{8}(?:-[\da-fA-F]{4}){3}-[\da-fA-F]{12}\b','[credential]',value)
                    result={'text':value}
                elif self.command=='GET' and (self.path in ('/version','/configs','/proxies','/connections','/rules','/providers/proxies','/providers/rules') or re.fullmatch(r'/proxies/[^/]+(?:/delay\?[^\r\n]+)?',self.path)):
                    result=engine.core(self.command,self.path)
                elif self.command=='PATCH' and self.path=='/configs' and isinstance(body,dict) and set(body)=={'mode'} and body['mode'] in ('rule','global','direct'):
                    result=engine.core('PATCH','/configs',body); engine.state['mode']=body['mode']; engine.write_config()
                elif self.command=='PUT' and re.fullmatch(r'/proxies/[^/]+',self.path) and isinstance(body,dict) and set(body)=={'name'}:
                    result=engine.core('PUT',self.path,body)
                elif self.command=='DELETE' and re.fullmatch(r'/connections(?:/[A-Za-z0-9-]+)?',self.path): result=engine.core('DELETE',self.path)
                else: raise ValueError('此接口未开放')
        except (ValueError, OSError, subprocess.SubprocessError):
            status=409
            # Known failures are actionable but never include source configs/URLs.
            import sys
            err=sys.exc_info()[1]
            result={'detail':str(err) if isinstance(err,ValueError) else '内核不可用，请查看日志后重试'}
        raw=json.dumps(result,ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home',type=Path,required=True)
    parser.add_argument('--binary',type=Path,required=True)
    parser.add_argument('--socket',type=Path,required=True)
    parser.add_argument('--uid',type=int,required=True)
    args=parser.parse_args()
    if args.socket.exists():
        import socket
        with socket.socket(socket.AF_UNIX) as s:
            if s.connect_ex(str(args.socket))==0: raise SystemExit('代理服务已经运行')
        args.socket.unlink()
    engine=Engine(args.home,args.binary)
    try:
        with Server(str(args.socket),Handler) as server:
            server.engine=engine
            os.chmod(args.socket,0o600)
            if os.geteuid()==0: os.chown(args.socket,args.uid,-1)
            def shutdown(*_): raise KeyboardInterrupt()
            signal.signal(signal.SIGTERM,shutdown); signal.signal(signal.SIGINT,shutdown)
            try: server.serve_forever(poll_interval=.5)
            except KeyboardInterrupt: pass
    finally:
        engine.stop(); args.socket.unlink(missing_ok=True)


if __name__=='__main__': main()
