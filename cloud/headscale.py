"""Owner-scoped mesh enrollment through the installed OpenSSH-independent CLI."""

import json
import os
import subprocess
import threading
from fastapi import HTTPException
from cloud.store import database

lock = threading.RLock()


def enabled():
    return os.environ.get("ORH_HEADSCALE_ENABLED") == "1"


def command(arguments):
    executable = os.environ.get("ORH_HEADSCALE_BIN", "/usr/local/bin/headscale")
    configuration = os.environ.get(
        "ORH_HEADSCALE_CLIENT_CONFIG", "/service/cloud/headscale-client.yaml"
    )
    try:
        result = subprocess.run(
            [executable, "-c", configuration, "-o", "json", *arguments],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        return (
            json.loads(result.stdout)
            if result.stdout.strip().startswith(("{", "["))
            else None
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        raise HTTPException(
            503, "组网控制服务暂不可用，请检查 headscale 服务和 socket"
        ) from None


def user_for(owner_id):
    if not enabled():
        raise HTTPException(503, "Cloud 组网服务尚未启用")
    with lock:
        with database() as db:
            row = db.execute(
                "SELECT hs_id FROM mesh_users WHERE account_id=?", (owner_id,)
            ).fetchone()
            account = db.execute(
                "SELECT username FROM users WHERE id=?", (owner_id,)
            ).fetchone()
        if row:
            return row["hs_id"]
        if not account:
            raise HTTPException(401, "账号已失效")
        existing = command(["users", "list"])
        legacy = os.environ.get("ORH_HEADSCALE_LEGACY_ACCOUNT") == account["username"]
        legacy_id = int(os.environ.get("ORH_HEADSCALE_LEGACY_USER_ID", "0"))
        name = "orh-" + owner_id
        chosen = (
            next((user for user in existing if user["id"] == legacy_id), None)
            if legacy
            else next((user for user in existing if user["name"] == name), None)
        )
        if chosen is None:
            chosen = command(["users", "create", name])
        identifier = int(chosen["id"])
        with database() as db:
            db.execute(
                "INSERT INTO mesh_users(account_id,hs_id) VALUES (?,?)",
                (owner_id, identifier),
            )
        return identifier


def preauth(device):
    with lock:
        user = user_for(device["owner_id"])
        result = command(
            ["preauthkeys", "create", "--user", str(user), "--expiration", "10m"]
        )
        return dict(
            key=result["key"],
            expires_in=600,
            control_url=os.environ.get(
                "ORH_HEADSCALE_PUBLIC_URL", "https://hs.openremotehub.top"
            ),
        )


def reconcile(device, node_key, services, paths):
    with lock:
        owner = user_for(device["owner_id"])
        node = next(
            (
                item
                for item in command(["nodes", "list"])
                if item["node_key"] == node_key
            ),
            None,
        )
        if not node or int(node["user"]["id"]) != owner:
            raise HTTPException(403, "此组网节点不属于设备绑定的账号")
        identifier = int(node["id"])
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            # An already-mapped node cannot be claimed by another device.
            collision = db.execute(
                "SELECT device_id FROM mesh_nodes WHERE hs_node_id=? AND device_id<>?",
                (identifier, device["instance_id"]),
            ).fetchone()
            if collision:
                raise HTTPException(409, "此节点已关联其他设备")
            old = db.execute(
                "SELECT hs_node_id FROM mesh_nodes WHERE device_id=?",
                (device["instance_id"],),
            ).fetchone()
            if old and old["hs_node_id"] != identifier:
                previous = next(
                    (
                        item
                        for item in command(["nodes", "list"])
                        if int(item["id"]) == old["hs_node_id"]
                    ),
                    None,
                )
                if previous and int(previous["user"]["id"]) == owner:
                    command(
                        [
                            "nodes",
                            "delete",
                            "--identifier",
                            str(old["hs_node_id"]),
                            "--force",
                        ]
                    )
            db.execute(
                "INSERT INTO mesh_nodes(device_id,hs_node_id,node_key,ips,services,paths) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(device_id) DO UPDATE SET hs_node_id=excluded.hs_node_id,node_key=excluded.node_key,ips=excluded.ips,services=excluded.services,paths=excluded.paths",
                (
                    device["instance_id"],
                    identifier,
                    node_key,
                    json.dumps(node["ip_addresses"]),
                    json.dumps(services),
                    json.dumps(paths),
                ),
            )
        return dict(ok=True, ips=node["ip_addresses"])


def public_mesh(db, device_id):
    row = db.execute(
        "SELECT ips,services,paths FROM mesh_nodes WHERE device_id=?", (device_id,)
    ).fetchone()
    return (
        dict(
            ips=json.loads(row["ips"]),
            services=json.loads(row["services"]),
            paths=json.loads(row["paths"]),
        )
        if row
        else None
    )


def delete_device(db, device_id):
    row = db.execute(
        "SELECT mesh_nodes.hs_node_id,mesh_users.hs_id FROM mesh_nodes JOIN devices ON devices.instance_id=mesh_nodes.device_id "
        "JOIN mesh_users ON mesh_users.account_id=devices.owner_id WHERE device_id=?",
        (device_id,),
    ).fetchone()
    if row and enabled():
        node = next(
            (
                item
                for item in command(["nodes", "list"])
                if int(item["id"]) == row["hs_node_id"]
            ),
            None,
        )
        if node:
            if int(node["user"]["id"]) != row["hs_id"]:
                raise HTTPException(409, "组网节点归属已变化，请核对后再解绑")
            command(
                ["nodes", "delete", "--identifier", str(row["hs_node_id"]), "--force"]
            )


def delete_account(db, owner_id):
    row = db.execute(
        "SELECT hs_id FROM mesh_users WHERE account_id=?", (owner_id,)
    ).fetchone()
    if row and enabled():
        for node in command(["nodes", "list"]):
            if int(node["user"]["id"]) == row["hs_id"]:
                command(["nodes", "delete", "--identifier", str(node["id"]), "--force"])
        if any(int(user["id"]) == row["hs_id"] for user in command(["users", "list"])):
            command(["users", "destroy", "--identifier", str(row["hs_id"]), "--force"])
