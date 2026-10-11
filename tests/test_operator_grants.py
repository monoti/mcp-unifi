import asyncio
import json
import sqlite3
import time
from contextlib import closing

import httpx
import pytest
import respx

from mcp_unifi import audit
from mcp_unifi.authority import (
    CLIENTS,
    OPERATION,
    Authority,
    Operation,
    Target,
    intent_digest,
    principal,
)
from mcp_unifi.clients.errors import UniFiError
from mcp_unifi.clients.stubs import StubState
from mcp_unifi.clients.unifi import UniFiClient
from mcp_unifi.config import ControllerConfig, Settings
from mcp_unifi.dispatcher import build_registry
from mcp_unifi.server import build_server


@pytest.fixture
def authority(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    grants = tmp_path / "grants"
    grants.mkdir(mode=0o700)
    monkeypatch.setenv("MCP_UNIFI_STDIO_PRINCIPAL", "alice")
    return Authority(
        readonly=False,
        scopes={"alice": ["home"]},
        grants=grants,
        journal=tmp_path / "journal.sqlite",
    )


def grant(
    authority, operation, *, expiry=None, identity="alice", controller="home", site="default"
):
    digest = intent_digest(identity, controller, site, operation.tool, operation.arguments)
    path = authority.grants / "grant.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "id": "grant-one",
                "digest": digest,
                "principal": identity,
                "controller": controller,
                "site": site,
                "expires": expiry or time.time() + 300,
            }
        )
    )
    path.chmod(0o600)


async def test_exact_grant_consumes_durably_and_omits_secrets(authority):
    operation = Operation("alice", "update_wlan", {"passphrase": "synthetic-secret"})
    grant(authority, operation)
    token = OPERATION.set(operation)
    try:
        await authority.begin("home", "default")
        await authority.begin("home", "default")
        authority.complete(operation, "success")
    finally:
        OPERATION.reset(token)
    with closing(sqlite3.connect(authority.journal)) as connection:
        rows = connection.execute("SELECT intent,outcome FROM attempts").fetchall()
    assert len(rows) == 1
    assert "synthetic-secret" not in rows[0][0]
    assert rows[0][1] == "success"
    restarted = Authority(
        readonly=False, scopes=authority.scopes, grants=authority.grants, journal=authority.journal
    )
    token = OPERATION.set(Operation("alice", operation.tool, operation.arguments))
    try:
        with pytest.raises(UniFiError, match="already been consumed"):
            await restarted.begin("home", "default")
    finally:
        OPERATION.reset(token)


@pytest.mark.parametrize("change", ["secret", "principal", "controller", "site", "expiry"])
async def test_changed_intent_or_expiry_cannot_use_grant(authority, change):
    operation = Operation("alice", "update_wlan", {"passphrase": "first-secret"})
    grant(authority, operation, expiry=time.time() - 1 if change == "expiry" else None)
    if change == "secret":
        operation.arguments["passphrase"] = "second-secret"
    if change == "principal":
        operation.principal = "bob"
    token = OPERATION.set(operation)
    try:
        with pytest.raises(UniFiError):
            await authority.begin(
                "other" if change == "controller" else "home",
                "other" if change == "site" else "default",
            )
    finally:
        OPERATION.reset(token)
    assert not authority.journal.exists()


@respx.mock
async def test_registered_client_denial_has_no_network_effect(authority):
    client = UniFiClient("gateway.test", "synthetic")
    CLIENTS[client._client] = Target(authority, "home", "default")
    route = respx.post("https://gateway.test:443/proxy/network/api/s/default/rest/wlanconf").mock(
        return_value=httpx.Response(200, json={"data": [{"_id": "new"}]})
    )
    token = OPERATION.set(Operation("alice", "create_wlan", {"name": "test"}))
    try:
        with pytest.raises(UniFiError, match="No exact"):
            await client.create_wlan({"name": "test"})
        assert route.call_count == 0
        grant(authority, OPERATION.get())
        await client.create_wlan({"name": "test"})
        assert route.call_count == 1
    finally:
        OPERATION.reset(token)
        await client.aclose()


async def test_failed_audit_prevents_consumption_and_request(authority):
    class BrokenSink:
        async def write(self, event):
            raise OSError("synthetic-secret")

        async def aclose(self):
            pass

    audit.set_audit_log(audit.AuditLog(BrokenSink()))
    operation = Operation("alice", "update_wlan", {"name": "test"})
    grant(authority, operation)
    token = OPERATION.set(operation)
    try:
        with pytest.raises(UniFiError, match="Audit is unhealthy"):
            await authority.begin("home", "default")
    finally:
        OPERATION.reset(token)
    assert not authority.journal.exists()


async def test_grant_expiring_during_audit_cannot_be_consumed(authority, monkeypatch):
    expiry = time.time() + 300

    class DelayedSink:
        async def write(self, event):
            monkeypatch.setattr(time, "time", lambda: expiry + 1)

        async def aclose(self):
            pass

    operation = Operation("alice", "create_vlan", {"name": "test"})
    grant(authority, operation, expiry=expiry)
    audit.set_audit_log(audit.AuditLog(DelayedSink()))
    token = OPERATION.set(operation)
    try:
        with pytest.raises(UniFiError, match="expired before"):
            await authority.begin("home", "default")
    finally:
        OPERATION.reset(token)
    assert not authority.journal.exists()


async def test_confirmation_is_bound_to_issuer(monkeypatch):
    settings = Settings(stub_mode=True, readonly=False, auth_required=False)
    state = StubState()
    server = build_server(settings, stub=state)
    monkeypatch.setenv("MCP_UNIFI_STDIO_PRINCIPAL", "alice")
    preview = await server.call_tool("delete_vlan", {"network_id": state.networks[0]["_id"]})
    payload = json.loads(preview.content[0].text)
    monkeypatch.setenv("MCP_UNIFI_STDIO_PRINCIPAL", "bob")
    refusal = await server.call_tool("confirm_destructive_action", {"token": payload["token"]})
    assert "another caller" in refusal.content[0].text
    monkeypatch.setenv("MCP_UNIFI_STDIO_PRINCIPAL", "alice")
    result = await server.call_tool("confirm_destructive_action", {"token": payload["token"]})
    assert '"deleted": true' in result.content[0].text


async def test_concurrent_operations_consume_one_grant(authority):
    original = Operation("alice", "create_vlan", {"name": "test"})
    grant(authority, original)

    async def attempt():
        operation = Operation("alice", original.tool, original.arguments)
        token = OPERATION.set(operation)
        try:
            await authority.begin("home", "default")
            return True
        except UniFiError:
            return False
        finally:
            OPERATION.reset(token)

    assert sorted(await asyncio.gather(attempt(), attempt())) == [False, True]


async def test_failed_completion_blocks_later_writes(authority, monkeypatch):
    operation = Operation("alice", "create_vlan", {"name": "test"})
    grant(authority, operation)
    token = OPERATION.set(operation)
    try:
        await authority.begin("home", "default")

        def broken():
            raise sqlite3.OperationalError("synthetic-secret")

        monkeypatch.setattr(authority, "_connection", broken)
        with pytest.raises(UniFiError, match="uncertain") as caught:
            authority.complete(operation, "success")
        assert "synthetic-secret" not in str(caught.value)
        with pytest.raises(UniFiError, match="unavailable"):
            await authority.begin("home", "default")
    finally:
        OPERATION.reset(token)


def test_controller_scope_filters_registry_and_default_alias(monkeypatch):
    settings = Settings(
        stub_mode=True,
        controllers=[
            ControllerConfig(name="home", host="home.test", api_key="synthetic"),
            ControllerConfig(name="office", host="office.test", api_key="synthetic"),
        ],
        default_controller="office",
        controller_scopes={"alice": ["home"]},
    )
    registry = build_registry(settings)
    monkeypatch.setenv("MCP_UNIFI_STDIO_PRINCIPAL", "alice")
    assert registry.names() == ["home"]
    for getter in [registry.get, registry.get_protect, registry.get_access]:
        with pytest.raises(UniFiError, match="not authorized"):
            getter("default")
    assert registry.get("home") is not None
    monkeypatch.setenv("MCP_UNIFI_STDIO_PRINCIPAL", "unknown")
    assert registry.names() == []


def test_unauthenticated_http_cannot_inherit_stdio_identity(monkeypatch):
    from fastmcp.server import dependencies

    monkeypatch.setenv("MCP_UNIFI_STDIO_PRINCIPAL", "alice")
    monkeypatch.setattr(dependencies, "get_access_token", lambda: None)
    monkeypatch.setattr(dependencies, "get_http_request", lambda: object())
    assert principal() is None


async def test_readiness_tracks_audit_failure():
    class BrokenSink:
        async def write(self, event):
            raise OSError("synthetic-secret")

        async def aclose(self):
            pass

    server = build_server(Settings(stub_mode=True, auth_required=False))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(server.http_app()), base_url="http://test"
    ) as client:
        response = await client.get("/ready")
        assert response.status_code == 200
        audit.set_audit_log(audit.AuditLog(BrokenSink()))
        response = await client.get("/ready")
        assert response.status_code == 503
        assert "synthetic-secret" not in response.text


@respx.mock
async def test_confirmation_uses_original_exact_operator_grant(authority):
    from mcp_unifi.cli.approve import create_grant

    settings = Settings(
        stub_mode=False,
        readonly=False,
        controllers=[ControllerConfig(name="home", host="gateway.test", api_key="synthetic")],
        controller_scopes={"alice": ["home"]},
        approval_dir=authority.grants,
        mutation_journal=authority.journal,
    )
    server = build_server(settings)
    base = "https://gateway.test:443/proxy/network/api/s/default"
    respx.get(f"{base}/rest/networkconf").mock(
        return_value=httpx.Response(
            200, json={"data": [{"_id": "n1", "name": "Test", "purpose": "corporate"}]}
        )
    )
    deleted = respx.delete(f"{base}/rest/networkconf/n1").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    preview = await server.call_tool("delete_vlan", {"network_id": "n1"})
    token = json.loads(preview.content[0].text)["token"]
    denied = await server.call_tool("confirm_destructive_action", {"token": token})
    assert "No exact" in denied.content[0].text
    assert deleted.call_count == 0
    await create_grant(
        settings,
        identity="alice",
        controller="home",
        tool_name="delete_vlan",
        arguments={"network_id": "n1"},
        ttl=300,
    )
    preview = await server.call_tool("delete_vlan", {"network_id": "n1"})
    token = json.loads(preview.content[0].text)["token"]
    result = await server.call_tool("confirm_destructive_action", {"token": token})
    assert '"deleted": true' in result.content[0].text
    assert deleted.call_count == 1
    with closing(sqlite3.connect(authority.journal)) as connection:
        row = connection.execute("SELECT intent,outcome FROM attempts").fetchone()
    assert json.loads(row[0])["tool"] == "delete_vlan"
    assert row[1] == "success"


def test_operator_cli_hides_untrusted_validation_details(tmp_path, monkeypatch, capsys):
    from mcp_unifi.cli import approve

    secret = "synthetic-cli-secret"
    arguments = tmp_path / "arguments.json"
    arguments.write_text("{}")

    async def reject(*args, **kwargs):
        raise ValueError(secret)

    monkeypatch.setattr(approve, "create_grant", reject)
    monkeypatch.setattr(
        "sys.argv",
        [
            "mcp-unifi-approve",
            "--principal",
            "alice",
            "--controller",
            "home",
            "--tool",
            "block_client",
            "--arguments-file",
            str(arguments),
        ],
    )
    with pytest.raises(SystemExit) as raised:
        approve.main()
    assert raised.value.code == 2
    output = capsys.readouterr()
    assert secret not in output.err + output.out
    assert "Approval failed" in output.err


def test_journal_uses_directory_durable_sqlite_settings(authority):
    with authority._connection() as connection:
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 3
        assert connection.execute("PRAGMA fullfsync").fetchone()[0] == 1
    connection.close()


async def test_journal_directory_sync_failure_blocks_consumption(authority, monkeypatch):
    import os
    import stat

    original_sync = os.fsync

    def fail_directory_sync(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("synthetic directory durability failure")
        original_sync(descriptor)

    operation = Operation("alice", "create_vlan", {"name": "test"})
    grant(authority, operation)
    monkeypatch.setattr(os, "fsync", fail_directory_sync)
    token = OPERATION.set(operation)
    try:
        with pytest.raises(UniFiError):
            await authority.begin("home", "default")
    finally:
        OPERATION.reset(token)
    assert authority.healthy is False
    assert not operation.attempts
    with closing(sqlite3.connect(authority.journal)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
