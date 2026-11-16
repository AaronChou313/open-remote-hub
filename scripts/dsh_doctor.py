"""Doctor for the console -> DSH Web chain.

Answers the same questions the "DeepSeek Harness" pane answers, in one command:
is the native host listening, does it accept our stored cookie, and would the
authenticated gateway succeed. Read-only by default; --fix only re-exchanges the
stored launch token; --restart also restarts the console service so a stale
in-process check cannot outlive the repair.
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
os.chdir(root)


def listening(port):
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def cookie_record(data):
    path = data / "dsh-auth.json"
    try:
        record = json.loads(path.read_text())
        return dict(present=bool(record.get("cookie")), port=record.get("port"), age=round(time.time() - path.stat().st_mtime))
    except (OSError, ValueError):
        return dict(present=False, port=None, age=None)


def snapshot():
    from app import dsh, main

    cfg = dsh.settings()
    record = cookie_record(main.DATA)
    owner = dsh.managed()
    native = owner or dsh.listener()
    health = dsh.healthy()
    return dict(
        enabled=cfg["enabled"],
        port=cfg["port"],
        gateway_port=cfg["gateway_port"],
        console_port=main.PORT,
        upstream=listening(cfg["port"]),
        gateway=listening(cfg["gateway_port"]),
        pid=native.pid if native else None,
        managed=bool(owner),
        cookie=record,
        healthy=health,
    )


def line(report):
    def mark(value):
        return "ok" if value else "FAIL"

    native = report["pid"] or "-"
    cookie = "present" if report["cookie"]["present"] else "missing"
    return "\n".join(
        [
            f"  enabled         {report['enabled']}",
            f"  native port     {report['port']} {mark(report['upstream'])}",
            f"  native pid      {native} (managed={report['managed']})",
            f"  native cookie   {cookie} (port={report['cookie']['port']}, age={report['cookie']['age']}s)",
            f"  native healthy  {mark(report['healthy'])}",
            f"  gateway port    {report['gateway_port']} {mark(report['gateway'])}",
        ]
    )


def restart_console(port, wait=15):
    if sys.platform != "darwin":
        return False
    label = "top.openremotehub.agent" if (Path.home()/"Library/LaunchAgents/top.openremotehub.agent.plist").exists() else "local.openremotehub"
    result = subprocess.run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{label}"], capture_output=True, text=True)
    if result.returncode != 0:
        return False
    deadline = time.time() + wait
    while time.time() < deadline:
        if listening(port):
            return True
        time.sleep(0.3)
    return listening(port)


def main_():
    parser = argparse.ArgumentParser(description="Diagnose the console DSH Web chain.")
    parser.add_argument("--fix", action="store_true", help="re-exchange the stored launch token when the cookie is stale")
    parser.add_argument("--restart", action="store_true", help="restart the console service if the repair does not take")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    before = snapshot()
    if not args.json:
        print("DSH chain:")
        print(line(before))

    acted = []
    if args.fix and before["enabled"] and before["upstream"] and not before["healthy"]:
        from app import dsh

        acted.append("recover" if dsh.recover() else "recover-failed")
        time.sleep(0.2)
    after = snapshot()

    if args.restart and not after["healthy"]:
        acted.append("restart-console" if restart_console(after["console_port"]) else "restart-failed")
        time.sleep(1)
        after = snapshot()

    if args.json:
        print(json.dumps(dict(before=before, after=after, acted=acted), ensure_ascii=False))
    elif acted:
        print("\nAfter repair:")
        print(line(after))
        print("  actions         " + ", ".join(acted))

    ok = after["enabled"] and after["upstream"] and after["healthy"]
    if not ok and not args.json:
        print("\n未恢复。按顺序排查：")
        print("  1. 重启控制台：launchctl kickstart -k gui/$(id -u)/local.openremotehub")
        print("  2. 仍失败再看本机私有日志：.runtime/dsh.log 与 .runtime/launchd.log")
        print("  3. 详见 docs/dsh-recovery.md")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main_())
