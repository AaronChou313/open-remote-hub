"""Owner scoping and lifecycle of mesh enrollment and invitation registration."""

import concurrent.futures
import json
import secrets
from types import SimpleNamespace
import pytest
from cloud import headscale, invite
from cloud.store import database
from test_cloud import cloud, signup, bind_device


@pytest.fixture
def mesh(cloud, monkeypatch):
    monkeypatch.setenv("ORH_HEADSCALE_ENABLED", "1")
    monkeypatch.setenv("ORH_CLOUD_INVITE_REQUIRED", "0")
    users = []
    nodes = []
    calls = []

    def command(args):
        calls.append(args)
        if args[:2] == ["users", "list"]:
            return list(users)
        if args[:2] == ["users", "create"]:
            row = {"id": len(users) + 1, "name": args[2]}
            users.append(row)
            return row
        if args[:2] == ["preauthkeys", "create"]:
            return {"key": "one-use-test-key"}
        if args[:2] == ["nodes", "list"]:
            return list(nodes)
        if args[:2] == ["nodes", "delete"]:
            nodes[:] = [node for node in nodes if node["id"] != int(args[3])]
            return None
        if args[:2] == ["users", "destroy"]:
            users[:] = [user for user in users if user["id"] != int(args[3])]
            return None
        pytest.fail("Unexpected headscale operation " + str(args))

    monkeypatch.setattr(headscale, "command", command)
    return cloud, users, nodes, calls


def test_mesh_enrollment_directory_scope_unbind_and_account_delete(mesh):
    client, users, nodes, calls = mesh
    first, first_user = signup(client, "mesh-owner-a")
    second, second_user = signup(client, "mesh-owner-b")
    a, agent_a, _ = bind_device(client, first)
    b, agent_b, _ = bind_device(client, second)
    for credentials in (agent_a, agent_b):
        response = client.post("/agent/preauth", headers=credentials, json={})
        assert response.status_code == 200 and response.json()["expires_in"] == 600
    assert len(users) == 2
    assert (
        client.post(
            "/api/devices/" + a["instance_id"] + "/preauth", headers=second, json={}
        ).status_code
        == 404
    )
    assert ["preauthkeys", "create", "--user", "1", "--expiration", "10m"] in calls
    assert all("--reusable" not in args for args in calls)
    nodes.extend(
        [
            {
                "id": 11,
                "node_key": "nodekey:" + "a" * 64,
                "user": {"id": 1},
                "ip_addresses": ["100.64.0.11"],
            },
            {
                "id": 12,
                "node_key": "nodekey:" + "b" * 64,
                "user": {"id": 2},
                "ip_addresses": ["100.64.0.12"],
            },
        ]
    )
    assert (
        client.post(
            "/agent/reconcile", headers=agent_a, json={"node_key": nodes[1]["node_key"]}
        ).status_code
        == 403
    )
    for credentials, node in [(agent_a, nodes[0]), (agent_b, nodes[1])]:
        assert (
            client.post(
                "/agent/reconcile",
                headers=credentials,
                json={
                    "node_key": node["node_key"],
                    "services": [8765, 21118],
                    "paths": ["direct"],
                },
            ).status_code
            == 200
        )
    rows = client.get("/agent/directory", headers=agent_a).json()
    assert len(rows) == 1 and rows[0]["instance_id"] == a["instance_id"]
    assert rows[0]["mesh"]["ips"] == ["100.64.0.11"] and rows[0]["mesh"]["paths"] == [
        "direct"
    ]
    assert (
        client.delete("/api/devices/" + a["instance_id"], headers=first).status_code
        == 200
    )
    assert all(node["id"] != 11 for node in nodes)
    assert client.get("/agent/directory", headers=agent_a).status_code == 401
    assert (
        client.request(
            "DELETE", "/api/account", headers=second, json={"confirm": False}
        ).status_code
        == 400
    )
    assert (
        client.request(
            "DELETE", "/api/account", headers=second, json={"confirm": True}
        ).status_code
        == 200
    )
    assert all(user["id"] != 2 for user in users) and all(
        node["id"] != 12 for node in nodes
    )
    assert client.get("/api/me", headers=second).status_code == 401
    assert client.get("/api/me", headers=first).status_code == 200


def test_invitation_single_consumption_and_expiry(cloud, monkeypatch):
    monkeypatch.setenv("ORH_CLOUD_INVITE_REQUIRED", "1")
    assert (
        cloud.post(
            "/api/register", json={"username": "no-invitation", "password": "1"}
        ).status_code
        == 403
    )
    code = invite.create()

    def register(index):
        return cloud.post(
            "/api/register",
            json={
                "username": "invited-" + str(index),
                "password": "1",
                "invitation": code,
            },
        ).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(register, range(2))) == [200, 403]
    expired = invite.create(-1)
    assert (
        cloud.post(
            "/api/register",
            json={"username": "expired-invite", "password": "1", "invitation": expired},
        ).status_code
        == 403
    )


def test_headscale_command_uses_argv_and_redacts_errors(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout='{"key":"isolated-fixture"}')

    monkeypatch.setattr(headscale.subprocess, "run", run)
    assert (
        headscale.command(
            ["preauthkeys", "create", "--user", "1", "--expiration", "10m"]
        )["key"]
        == "isolated-fixture"
    )
    assert isinstance(calls[0][0], list) and not calls[0][1].get("shell", False)

    def broken(*args, **kwargs):
        raise headscale.subprocess.CalledProcessError(
            1, args[0], stderr="SECRET-CLI-OUTPUT"
        )

    monkeypatch.setattr(headscale.subprocess, "run", broken)
    with pytest.raises(Exception) as error:
        headscale.command(["nodes", "list"])
    assert "SECRET-CLI-OUTPUT" not in str(error.value)
