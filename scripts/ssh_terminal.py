"""Runs only inside a newly created, owned Zellij pane. No passwords in storage."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

# A fixed POSIX script receives one validated public key on stdin. Authentication
# still reads /dev/tty, which is the protected native Zellij Web terminal.
DEPLOY = '''set -eu
umask 077
cd "$HOME"
if [ -L .ssh ] || [ -L .ssh/authorized_keys ]; then
  echo 'Refusing symbolic-link SSH destinations' >&2; exit 41
fi
mkdir -p .ssh
chmod 700 .ssh
count=0
until mkdir .ssh/.openremotehub-deploy-lock 2>/dev/null; do
  count=$((count+1)); [ "$count" -lt 10 ] || exit 42; sleep 1
done
trap 'rmdir .ssh/.openremotehub-deploy-lock' EXIT HUP INT TERM
IFS= read -r key
set -f
set -- $key
type=$1; blob=$2
touch .ssh/authorized_keys
chmod 600 .ssh/authorized_keys
if awk -v t="$type" -v b="$blob" '{for(i=1;i<NF;i++) if($i==t && $(i+1)==b) found=1} END {exit !found}' .ssh/authorized_keys; then
  printf 'Public key already installed\\n'
else
  printf '\\n%s\\n' "$key" >> .ssh/authorized_keys
  printf 'Public key installed\\n'
fi
'''


def execute(launch, data, ssh_dir):
    os.environ['ORH_SSH_DIR'] = ssh_dir
    from app import main
    main.DATA = Path(data)
    from app.ssh import storage as store, configuration as config
    from app.ssh.terminals import argv
    from app.ssh.keys import public_line
    from app.ssh.process import environment
    import psutil
    row = store.get('terminal', launch)
    if not row or time.time() - row['created'] > 60 or row['state'] != 'starting':
        print('启动请求已使用或过期，请在控制台重新连接。')
        return 2
    if config.discover()['signature'] != row['signature']:
        row['state'] = 'config_changed'
        store.put('terminal', launch, row)
        print('SSH 配置已经改变，请回控制台重新连接。')
        return 2
    config.checked_sources()
    row.update(state='running', pid=os.getpid(), process_created=psutil.Process().create_time())
    store.put('terminal', launch, row)
    code = 1
    try:
        if row.get('key'):
            public = public_line(store.read(store.path(row['key'] + '.pub')).decode())['public']
            import shlex
            command = argv(row['host'])
            index = command.index('--')
            command[index:index] = ['-o', 'PreferredAuthentications=publickey,keyboard-interactive,password',
                                    '-o', 'PubkeyAuthentication=yes', '-o', 'PasswordAuthentication=yes',
                                    '-o', 'KbdInteractiveAuthentication=yes']
            command += ['sh -c ' + shlex.quote(DEPLOY)]
            result = subprocess.run(command, input=(public + '\n').encode(), env=environment())
            if result.returncode:
                print('\n公钥部署失败，请核验主机指纹、密码和远端文件权限，然后重新部署。')
                code = result.returncode
            else:
                print('\n正在验证公钥认证。加密私钥可能需要在此输入口令。')
                command = argv(row['host'], identity=row['key'])
                # Options must precede -- and the host, not become a remote command.
                index = command.index('--')
                command[index:index] = ['-o', 'PasswordAuthentication=no', '-o', 'KbdInteractiveAuthentication=no',
                                        '-o', 'PreferredAuthentications=publickey', '-o', 'StrictHostKeyChecking=yes']
                code = subprocess.run(command + ['true'], env=environment()).returncode
                print('\n公钥认证验证成功。' if code == 0 else '\n公钥已部署，但认证验证失败。请检查目标 SSH 授权策略或密钥口令。')
        else:
            code = subprocess.run(argv(row['host']), env=environment()).returncode
            print('\nSSH 已断开。需要继续时，请在控制台点击重新连接。')
    finally:
        row.update(state='completed' if code == 0 else 'failed', exit_code=code, ended=time.time())
        store.put('terminal', launch, row)
    return code


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True)
    parser.add_argument('--ssh-dir', required=True)
    parser.add_argument('--launch', required=True)
    args = parser.parse_args()
    try:
        sys.exit(execute(args.launch, args.data, args.ssh_dir))
    except Exception:
        # Private paths, key contents and process transcripts must not enter errors.
        print('SSH 启动失败，请返回控制台检查配置与诊断结果。')
        sys.exit(1)
