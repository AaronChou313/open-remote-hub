"""Bounded OpenSSH processes. No shell or secret-bearing argv."""
import contextlib
import os
from pathlib import Path
import pty
import re
import select
import signal
import subprocess
import termios
import time

from fastapi import HTTPException


class CommandFailure(Exception):
    def __init__(self, code, output):
        self.code = code
        self.output = output


def environment():
    env = {k: v for k, v in os.environ.items() if not k.startswith(('ORH_', 'SSH_ASKPASS'))}
    env.update(LC_ALL='C', LANG='C', SSH_ASKPASS_REQUIRE='never')
    return env


def run(argv, timeout=12, cancel=None, input_data=None):
    process = subprocess.Popen(argv, stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               env=environment(), cwd=Path.home(), start_new_session=True)
    end = time.monotonic() + timeout
    output = bytearray()
    try:
        if input_data is not None:
            process.stdin.write(input_data)
            process.stdin.close()
        while True:
            if cancel and cancel.is_set():
                raise HTTPException(409, '诊断已取消')
            if time.monotonic() > end:
                raise HTTPException(504, 'SSH 操作超时')
            readable, _, _ = select.select([process.stdout], [], [], 0.1)
            if readable:
                chunk = os.read(process.stdout.fileno(), 16384)
                output.extend(chunk)
                if len(output) > 256 * 1024:
                    raise HTTPException(413, 'SSH 输出超过上限')
                if not chunk:
                    break
        process.wait(timeout=1)
        text = output.decode('utf-8', errors='replace')
        if process.returncode:
            raise CommandFailure(process.returncode, text)
        return text
    finally:
        if process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        process.stdout.close()


def keygen(argv, answers, timeout=20):
    """Answer ssh-keygen prompts over a no-echo PTY. Never retain its transcript."""
    master, slave = pty.openpty()
    attrs = termios.tcgetattr(slave)
    attrs[3] &= ~termios.ECHO
    termios.tcsetattr(slave, termios.TCSANOW, attrs)
    process = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave,
                               env=environment(), cwd=Path.home(), start_new_session=True)
    os.close(slave)
    pending = ''
    public = []
    index = 0
    end = time.monotonic() + timeout
    try:
        while time.monotonic() < end:
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    raw = os.read(master, 8192)
                except OSError:
                    break
                if not raw:
                    break
                pending += raw.decode(errors='replace')
                if len(pending) > 65536:
                    raise HTTPException(400, '密钥操作输出异常')
                if re.search(r'(?:passphrase.*[:?]|again:|same passphrase again:|password.*:)[ \t]*$', pending, re.I):
                    if index >= len(answers):
                        raise HTTPException(400, '密钥口令错误或需要额外口令')
                    answer = answers[index]
                    if any(c in answer for c in '\x00\r\n') or len(answer.encode()) > 1024:
                        raise HTTPException(400, '密钥口令格式无效')
                    os.write(master, answer.encode() + b'\n')
                    index += 1
                    pending = ''
            if process.poll() is not None and not ready:
                break
        else:
            raise HTTPException(504, '密钥操作超时')
        process.wait(timeout=2)
        if process.returncode:
            raise HTTPException(400, '密钥格式或口令无效，操作未完成')
        for line in pending.splitlines():
            if re.match(r'^(ssh-|ecdsa-|sk-)', line):
                public.append(line.strip())
        return '\n'.join(public)
    finally:
        if process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        os.close(master)
