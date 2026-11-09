"""Bounded argv-only queries. Never invoke a shell or read process-wide secrets."""
import os
import selectors
import shutil
import signal
import subprocess
import sys
import time
from fastapi import HTTPException


def run(argv,cwd_fd=None,timeout=8,limit=256*1024,extra_env=None):
    env={k:v for k,v in os.environ.items() if not k.startswith(('ORH_','GIT_'))}
    env.update({'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull,'GIT_OPTIONAL_LOCKS':'0','GIT_TERMINAL_PROMPT':'0','HOMEBREW_NO_AUTO_UPDATE':'1','HOMEBREW_NO_ANALYTICS':'1','CONDA_NO_PLUGINS':'true','PIP_DISABLE_PIP_VERSION_CHECK':'1','TERM':'dumb'})
    env.update(extra_env or {})
    env['PATH']=os.pathsep.join(p for p in env.get('PATH',os.defpath).split(os.pathsep) if os.path.isabs(p))
    if not os.path.isabs(argv[0]):
        binary=shutil.which(argv[0],path=env['PATH'])
        if not binary:raise HTTPException(503,'工具未安装：'+argv[0])
        argv=[binary,*argv[1:]]
    if cwd_fd is not None:
        # macOS /dev/fd/N cannot be chdir'ed. fchdir in a tiny isolated child
        # avoids unsafe preexec_fn in this multithreaded server.
        argv=[sys.executable,'-I','-c','import os,sys;os.fchdir(int(sys.argv[1]));os.execvpe(sys.argv[2],sys.argv[2:],os.environ)',str(cwd_fd),*argv]
    try:
        p=subprocess.Popen(argv,pass_fds=(cwd_fd,) if cwd_fd is not None else (),env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
    except OSError as e:raise HTTPException(503,'工具不可用：'+str(e))
    out=bytearray();truncated=False;done=False;deadline=time.monotonic()+timeout
    with selectors.DefaultSelector() as selector:
        selector.register(p.stdout,selectors.EVENT_READ)
        try:
            while selector.get_map():
                if time.monotonic()>deadline:raise HTTPException(504,'工具查询超时，未执行后续操作')
                for key,_ in selector.select(.1):
                    chunk=os.read(key.fileobj.fileno(),32768)
                    if not chunk:selector.unregister(key.fileobj);continue
                    out.extend(chunk[:max(0,limit-len(out))])
                    if len(out)>=limit:truncated=True;break
                if truncated:break
            if not truncated:
                try:p.wait(timeout=max(.1,deadline-time.monotonic()));done=True
                except subprocess.TimeoutExpired:raise HTTPException(504,'工具查询超时')
        finally:
            # A truncated query or inherited output pipe must not leave a helper running.
            if not done:
                try:os.killpg(p.pid,signal.SIGTERM)
                except ProcessLookupError:pass
            try:p.wait(1)
            except subprocess.TimeoutExpired:
                try:os.killpg(p.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                p.wait(2)
            p.stdout.close()
    value=out.decode('utf-8',errors='replace')
    if p.returncode and not truncated:raise HTTPException(422,value[:1500] or '工具查询失败')
    return {'output':value,'truncated':truncated}
