"""Prepare the ORN data plane that ORH owns: binary, config and identity.

Idempotent. Never disables a separately installed ORN service; that takeover is
an explicit action in the console so the mesh is never stopped by accident.
"""
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def env_file():
    return ROOT / '.env'


def read_env():
    values = {}
    path = env_file()
    if path.exists():
        for line in path.read_text().splitlines():
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip()
    return values


def write_env(values):
    path = env_file()
    lines = path.read_text().splitlines() if path.exists() else []
    remaining = dict(values)
    output = []
    for line in lines:
        if line and not line.startswith('#') and '=' in line:
            key = line.split('=', 1)[0].strip()
            if key in remaining:
                output.append(f'{key}={remaining.pop(key)}')
                continue
        output.append(line)
    for key, value in remaining.items():
        output.append(f'{key}={value}')
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as target:
        target.write('\n'.join(output) + '\n')
    temporary.replace(path)


def install_binary(source):
    name = 'orn-agent.exe' if sys.platform == 'win32' else 'orn-agent'
    destination = ROOT / 'bin' / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.resolve() == Path(source).resolve():
        return destination
    shutil.copy2(source, destination)
    destination.chmod(0o755)
    return destination


def main():
    from app import orn_runtime
    values = read_env()
    if values.get('ORH_ORN_ENABLED', 'auto').lower() in ('0', 'false', 'off', 'no'):
        print('ORN integration disabled by ORH_ORN_ENABLED; nothing to do.')
        return
    binary = orn_runtime.binary()
    if not binary:
        print('未找到 ORN Agent 二进制。请先构建 open-remote-net（dist/orn-agent-*），')
        print('或设置 ORH_ORN_BIN=/absolute/path/to/orn-agent 后重新运行本脚本。')
        return
    installed = install_binary(binary)
    configured = values.get('ORH_ORN_BIN', '').strip()
    changes = {}
    if not configured:
        changes['ORH_ORN_BIN'] = str(installed.relative_to(ROOT))
    config = orn_runtime.config_path()
    created = orn_runtime.ensure_config()
    if changes:
        write_env(changes)
    print(f'ORN 二进制：{installed}')
    print(f'ORN 配置：{config}{"（已创建）" if created else "（沿用现有身份与绑定）"}')
    service = orn_runtime.standalone_service()
    if service:
        kind = {'launchd': 'LaunchAgent', 'systemd': 'systemd 用户服务', 'scheduled-task': '计划任务'}.get(service[0], service[0])
        print(f'检测到独立 ORN 服务（{kind}）。本控制台会先观察它；')
        print('需要统一托管时，在“网络连接 → ORN”中点击“由 ORH 托管 ORN”。')
    else:
        print('启动 ORH 后将由控制台托管 ORN。')


if __name__ == '__main__':
    main()
