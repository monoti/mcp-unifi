import asyncio
import json
import sqlite3
import subprocess
import sys
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
    initialize_journal,
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
    subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "mcp_unifi.cli.journal",
            "init",
            "--path",
            str(tmp_path / "journal.sqlite"),
        ],
        check=True,
        capture_output=True,
    )
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
                "version": 2,
                "journal_id": authority.journal_id(),
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
    with closing(sqlite3.connect(authority.journal)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0


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
    with closing(sqlite3.connect(authority.journal)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0


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
    with closing(sqlite3.connect(authority.journal)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0


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


async def test_consumed_earlier_filename_does_not_shadow_fresh_grant(authority):
    operation = Operation("alice", "create_vlan", {"name": "test"})
    grant(authority, operation)
    old_path = authority.grants / "000-old.json"
    (authority.grants / "grant.json").rename(old_path)
    token = OPERATION.set(operation)
    try:
        await authority.begin("home", "default")
        authority.complete(operation, "success")
    finally:
        OPERATION.reset(token)
    fresh = json.loads(old_path.read_text())
    fresh["id"] = "fresh-grant"
    path = authority.grants / "999-fresh.json"
    path.write_text(json.dumps(fresh))
    path.chmod(0o600)
    restarted = Authority(
        readonly=False, scopes=authority.scopes, grants=authority.grants, journal=authority.journal
    )
    token = OPERATION.set(Operation("alice", operation.tool, operation.arguments))
    try:
        await restarted.begin("home", "default")
        restarted.complete(OPERATION.get(), "success")
    finally:
        OPERATION.reset(token)
    with closing(sqlite3.connect(authority.journal)) as connection:
        assert connection.execute(
            "SELECT grant_id,outcome FROM attempts ORDER BY grant_id"
        ).fetchall() == [("fresh-grant", "success"), ("grant-one", "success")]
    token = OPERATION.set(Operation("alice", operation.tool, operation.arguments))
    try:
        with pytest.raises(UniFiError, match="already been consumed"):
            await restarted.begin("home", "default")
    finally:
        OPERATION.reset(token)


@pytest.mark.parametrize("body_raises", [False, True])
@respx.mock
async def test_cancelled_completion_blocks_readiness_and_later_requests(
    authority, monkeypatch, body_raises
):
    from mcp_unifi import server as server_module
    from mcp_unifi.modules import _audit

    completion_entered = asyncio.Event()
    context_after = []

    class BlockedCompletionSink:
        async def write(self, event):
            if event.result != {"phase": "intent"}:
                completion_entered.set()
                await asyncio.Event().wait()

        async def aclose(self):
            pass

    client = UniFiClient("gateway.test", "synthetic")
    CLIENTS[client._client] = Target(authority, "home", "default")
    route = respx.post("https://gateway.test:443/proxy/network/api/s/default/rest/wlanconf").mock(
        return_value=httpx.Response(200, json={"data": [{"_id": "new"}]})
    )

    @_audit.audited("completion_cancel_probe", mutates=True)
    async def mutation():
        await client.create_wlan({"name": "test"})
        if body_raises:
            raise RuntimeError("synthetic tool failure")
        return {"created": True}

    operation = Operation("alice", "completion_cancel_probe", {})
    grant(authority, operation)
    registry = build_registry(Settings(stub_mode=True))
    registry.authority = authority
    monkeypatch.setattr(server_module, "build_registry", lambda *args, **kwargs: registry)
    server = build_server(Settings(stub_mode=True, readonly=False, auth_required=False))
    audit.set_audit_log(audit.AuditLog(BlockedCompletionSink()))

    async def invoke():
        try:
            await mutation()
        finally:
            context_after.append((OPERATION.get(), _audit._ANNOTATIONS.get()))

    task = asyncio.create_task(invoke())
    try:
        await asyncio.wait_for(completion_entered.wait(), timeout=5)
        assert route.call_count == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=5)
        assert context_after == [(None, None)]
        assert authority.healthy is False
        audit.set_audit_log(None)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(server.http_app()), base_url="http://test"
        ) as http_client:
            assert (await http_client.get("/ready")).status_code == 503
        fresh = json.loads((authority.grants / "grant.json").read_text())
        fresh["id"] = "fresh-grant"
        (authority.grants / "grant.json").write_text(json.dumps(fresh))
        with pytest.raises(UniFiError, match="unavailable"):
            await mutation()
        assert route.call_count == 1
        with closing(sqlite3.connect(authority.journal)) as connection:
            assert connection.execute("SELECT outcome FROM attempts").fetchall() == [("uncertain",)]
    finally:
        task.cancel()
        await client.aclose()


@respx.mock
async def test_queued_intent_cannot_write_after_cancelled_completion(authority, monkeypatch):
    from mcp_unifi import server as server_module
    from mcp_unifi.modules._audit import audited

    completion_entered = asyncio.Event()
    intent_queued = asyncio.Event()

    class ObservedLock(asyncio.Lock):
        async def acquire(self):
            if self.locked():
                intent_queued.set()
            return await super().acquire()

    class BlockedCompletionSink:
        async def write(self, event):
            if event.result != {"phase": "intent"} and event.args.get("name") == "first":
                completion_entered.set()
                await asyncio.Event().wait()

        async def aclose(self):
            pass

    client = UniFiClient("gateway.test", "synthetic")
    CLIENTS[client._client] = Target(authority, "home", "default")
    route = respx.post("https://gateway.test:443/proxy/network/api/s/default/rest/wlanconf").mock(
        return_value=httpx.Response(200, json={"data": [{"_id": "new"}]})
    )

    @audited("queued_completion_probe", mutates=True)
    async def mutation(name):
        await client.create_wlan({"name": name})
        return {"created": True}

    grant(authority, Operation("alice", "queued_completion_probe", {"name": "first"}))
    (authority.grants / "grant.json").rename(authority.grants / "first.json")
    grant(authority, Operation("alice", "queued_completion_probe", {"name": "second"}))
    second_path = authority.grants / "grant.json"
    second_grant = json.loads(second_path.read_text())
    second_grant["id"] = "second-grant"
    second_path.write_text(json.dumps(second_grant))
    registry = build_registry(Settings(stub_mode=True))
    registry.authority = authority
    monkeypatch.setattr(server_module, "build_registry", lambda *args, **kwargs: registry)
    server = build_server(Settings(stub_mode=True, readonly=False, auth_required=False))
    log = audit.AuditLog(BlockedCompletionSink())
    log._lock = ObservedLock()
    audit.set_audit_log(log)
    first = asyncio.create_task(mutation(name="first"))
    second = None
    try:
        await asyncio.wait_for(completion_entered.wait(), timeout=5)
        assert route.call_count == 1
        second = asyncio.create_task(mutation(name="second"))
        await asyncio.wait_for(intent_queued.wait(), timeout=5)
        assert not second.done()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(first, timeout=5)
        assert authority.healthy is False
        assert log.healthy is True
        second_result = (
            await asyncio.wait_for(asyncio.gather(second, return_exceptions=True), timeout=5)
        )[0]
        assert route.call_count == 1
        assert isinstance(second_result, UniFiError)
        assert "unavailable" in str(second_result)
        with closing(sqlite3.connect(authority.journal)) as connection:
            assert connection.execute("SELECT grant_id,outcome FROM attempts").fetchall() == [
                ("grant-one", "uncertain")
            ]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(server.http_app()), base_url="http://test"
        ) as http_client:
            assert (await http_client.get("/ready")).status_code == 503
    finally:
        first.cancel()
        if second is not None:
            second.cancel()
        await asyncio.gather(
            first, *([second] if second is not None else []), return_exceptions=True
        )
        await client.aclose()


async def test_recorded_exception_outcome_keeps_authority_healthy(authority):
    from mcp_unifi.modules._audit import audited

    @audited("recorded_exception_probe", mutates=True)
    async def mutation():
        await authority.begin("home", "default")
        raise RuntimeError("synthetic tool failure")

    grant(authority, Operation("alice", "recorded_exception_probe", {}))
    with pytest.raises(RuntimeError, match="synthetic tool failure"):
        await mutation()
    assert authority.healthy is True
    assert OPERATION.get() is None
    with closing(sqlite3.connect(authority.journal)) as connection:
        assert connection.execute("SELECT outcome FROM attempts").fetchall() == [("uncertain",)]


@respx.mock
async def test_live_journal_loss_blocks_composite_backend_continuation(authority):
    client = UniFiClient("gateway.test", "synthetic")
    CLIENTS[client._client] = Target(authority, "home", "default")
    route = respx.post("https://gateway.test:443/proxy/network/api/s/default/rest/wlanconf").mock(
        return_value=httpx.Response(200, json={"data": [{"_id": "new"}]})
    )
    operation = Operation("alice", "composite_probe", {})
    grant(authority, operation)
    token = OPERATION.set(operation)
    try:
        await client.create_wlan({"name": "first"})
        assert route.call_count == 1
        authority.journal.unlink()
        with pytest.raises(UniFiError):
            await client.create_wlan({"name": "second"})
        assert route.call_count == 1
        assert authority.healthy is False
        assert not authority.journal.exists()
    finally:
        OPERATION.reset(token)
        await client.aclose()


@respx.mock
async def test_deleted_pending_row_makes_backend_outcome_uncertain(authority):
    client = UniFiClient("gateway.test", "synthetic")
    CLIENTS[client._client] = Target(authority, "home", "default")
    route = respx.post("https://gateway.test:443/proxy/network/api/s/default/rest/wlanconf").mock(
        return_value=httpx.Response(200, json={"data": [{"_id": "new"}]})
    )
    operation = Operation("alice", "completion_probe", {})
    grant(authority, operation)
    token = OPERATION.set(operation)
    try:
        await client.create_wlan({"name": "first"})
        assert route.call_count == 1
        with closing(sqlite3.connect(authority.journal)) as connection, connection:
            connection.execute("DELETE FROM attempts")
        with pytest.raises(UniFiError, match="uncertain"):
            authority.complete(operation, "success")
        assert authority.healthy is False
    finally:
        OPERATION.reset(token)
        await client.aclose()


@pytest.mark.parametrize("replacement", [False, True])
@respx.mock
async def test_journal_loss_between_calls_and_restart_never_replays(authority, replacement):
    client = UniFiClient("gateway.test", "synthetic")
    route = respx.post("https://gateway.test:443/proxy/network/api/s/default/rest/wlanconf").mock(
        return_value=httpx.Response(200, json={"data": [{"_id": "new"}]})
    )
    CLIENTS[client._client] = Target(authority, "home", "default")
    operation = Operation("alice", "recovery_probe", {})
    grant(authority, operation)
    token = OPERATION.set(operation)
    try:
        await client.create_wlan({"name": "first"})
        authority.complete(operation, "success")
        authority.journal.rename(authority.journal.with_suffix(".history"))
        if replacement:
            initialize_journal(authority.journal)
        OPERATION.set(Operation("alice", operation.tool, operation.arguments))
        with pytest.raises(UniFiError):
            await client.create_wlan({"name": "second"})
        assert route.call_count == 1
        assert authority.healthy is False
        restarted = Authority(
            readonly=False,
            scopes=authority.scopes,
            grants=authority.grants,
            journal=authority.journal,
        )
        CLIENTS[client._client] = Target(restarted, "home", "default")
        with pytest.raises(UniFiError):
            await client.create_wlan({"name": "third"})
        assert route.call_count == 1
        if not replacement:
            assert not authority.journal.exists()
    finally:
        OPERATION.reset(token)
        await client.aclose()


@respx.mock
async def test_new_generation_refuses_old_grant_and_fresh_cli_grant_succeeds_once(authority):
    from mcp_unifi.cli.approve import create_grant

    operation = Operation(
        "alice",
        "block_client",
        {"mac": "aa:bb:cc:00:00:01", "controller": "default", "dry_run": False},
    )
    grant(authority, operation)
    old_id = authority.journal_id()
    authority.journal.rename(authority.journal.with_suffix(".history"))
    initialize_journal(authority.journal)
    restarted = Authority(
        readonly=False, scopes=authority.scopes, grants=authority.grants, journal=authority.journal
    )
    assert restarted.journal_id() != old_id
    client = UniFiClient("gateway.test", "synthetic")
    CLIENTS[client._client] = Target(restarted, "home", "default")
    route = respx.post("https://gateway.test:443/proxy/network/api/s/default/cmd/stamgr").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    token = OPERATION.set(operation)
    try:
        with pytest.raises(UniFiError, match="No exact"):
            await client.block_client(operation.arguments["mac"])
        assert route.call_count == 0
        settings = Settings(
            stub_mode=False,
            readonly=False,
            controllers=[ControllerConfig(name="home", host="gateway.test", api_key="synthetic")],
            controller_scopes=authority.scopes,
            approval_dir=authority.grants,
            mutation_journal=authority.journal,
        )
        await create_grant(
            settings,
            identity="alice",
            controller="home",
            tool_name="block_client",
            arguments={"mac": operation.arguments["mac"]},
            ttl=300,
        )
        await client.block_client(operation.arguments["mac"])
        restarted.complete(operation, "success")
        OPERATION.set(Operation("alice", operation.tool, operation.arguments))
        with pytest.raises(UniFiError, match="consumed"):
            await client.block_client(operation.arguments["mac"])
        assert route.call_count == 1
        assert restarted.healthy is True
    finally:
        OPERATION.reset(token)
        await client.aclose()


@pytest.mark.parametrize("damage", ["schema", "generation", "metadata", "trigger", "v1"])
async def test_invalid_journal_or_v1_grant_is_refused(authority, damage):
    operation = Operation("alice", "probe", {})
    grant(authority, operation)
    if damage == "v1":
        path = authority.grants / "grant.json"
        value = json.loads(path.read_text())
        value["version"] = 1
        del value["journal_id"]
        path.write_text(json.dumps(value))
    else:
        with closing(sqlite3.connect(authority.journal)) as connection, connection:
            connection.execute(
                {
                    "schema": "DROP TABLE attempts",
                    "generation": "UPDATE journal_meta SET journal_id='invalid'",
                    "metadata": "DELETE FROM journal_meta",
                    "trigger": (
                        "CREATE TRIGGER erase AFTER INSERT ON attempts "
                        "BEGIN DELETE FROM attempts; END"
                    ),
                }[damage]
            )
    token = OPERATION.set(operation)
    try:
        with pytest.raises(UniFiError):
            await authority.begin("home", "default")
        assert not operation.attempts
        assert authority.healthy is (damage == "v1")
    finally:
        OPERATION.reset(token)


async def test_missing_state_server_and_issuer_do_not_create(tmp_path):
    from mcp_unifi.cli.approve import create_grant

    tmp_path.chmod(0o700)
    grants = tmp_path / "grants"
    grants.mkdir(mode=0o700)
    journal = tmp_path / "missing.sqlite"
    settings = Settings(
        stub_mode=False,
        readonly=False,
        auth_required=False,
        controllers=[ControllerConfig(name="home", host="gateway.test", api_key="synthetic")],
        controller_scopes={"alice": ["home"]},
        approval_dir=grants,
        mutation_journal=journal,
    )
    server = build_server(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(server.http_app()), base_url="http://test"
    ) as client:
        assert (await client.get("/ready")).status_code == 503
    with pytest.raises(UniFiError):
        await create_grant(
            settings,
            identity="alice",
            controller="home",
            tool_name="block_client",
            arguments={"mac": "aa:bb:cc:00:00:01"},
            ttl=300,
        )
    assert not journal.exists()
    assert list(grants.iterdir()) == []


@pytest.mark.parametrize("existing", ["file", "symlink", "fifo", "directory"])
def test_initializer_refuses_existing_paths_and_secure_path_requires_regular_files(
    tmp_path, existing
):
    import os

    from mcp_unifi.authority import secure_path

    tmp_path.chmod(0o700)
    path = tmp_path / "journal"
    if existing == "file":
        path.write_bytes(b"private history")
        path.chmod(0o600)
    elif existing == "symlink":
        path.symlink_to(tmp_path / "absent")
    elif existing == "fifo":
        os.mkfifo(path, 0o600)
    else:
        path.mkdir(mode=0o700)
    with pytest.raises(FileExistsError):
        initialize_journal(path)
    if existing == "file":
        assert path.read_bytes() == b"private history"
    else:
        with pytest.raises(UniFiError):
            secure_path(path)


@respx.mock
async def test_deleted_pending_row_blocks_composite_continuation(authority):
    client = UniFiClient("gateway.test", "synthetic")
    CLIENTS[client._client] = Target(authority, "home", "default")
    route = respx.post("https://gateway.test:443/proxy/network/api/s/default/rest/wlanconf").mock(
        return_value=httpx.Response(200, json={"data": [{"_id": "new"}]})
    )
    operation = Operation("alice", "composite_probe", {})
    grant(authority, operation)
    token = OPERATION.set(operation)
    try:
        await client.create_wlan({"name": "first"})
        with closing(sqlite3.connect(authority.journal)) as connection, connection:
            connection.execute("DELETE FROM attempts")
        with pytest.raises(UniFiError):
            await client.create_wlan({"name": "second"})
        assert route.call_count == 1
        assert authority.healthy is False
    finally:
        OPERATION.reset(token)
        await client.aclose()


@pytest.mark.parametrize("stage", ["continuation", "completion"])
@respx.mock
async def test_same_path_replacement_blocks_remaining_backend_or_completion(authority, stage):
    client = UniFiClient("gateway.test", "synthetic")
    CLIENTS[client._client] = Target(authority, "home", "default")
    route = respx.post("https://gateway.test:443/proxy/network/api/s/default/rest/wlanconf").mock(
        return_value=httpx.Response(200, json={"data": [{"_id": "new"}]})
    )
    operation = Operation("alice", "replace_probe", {})
    grant(authority, operation)
    token = OPERATION.set(operation)
    try:
        await client.create_wlan({"name": "first"})
        authority.journal.rename(authority.journal.with_suffix(".history"))
        initialize_journal(authority.journal)
        with pytest.raises(UniFiError):
            if stage == "continuation":
                await client.create_wlan({"name": "second"})
            else:
                authority.complete(operation, "success")
        assert route.call_count == 1
        assert authority.healthy is False
        authority.journal.unlink()
        authority.journal.with_suffix(".history").rename(authority.journal)
        with pytest.raises(UniFiError, match="unavailable"):
            await client.create_wlan({"name": "third"})
        assert route.call_count == 1
    finally:
        OPERATION.reset(token)
        await client.aclose()


def test_initialization_failure_preserves_unusable_file_for_inspection(tmp_path, monkeypatch):
    import os

    tmp_path.chmod(0o700)
    journal = tmp_path / "journal.sqlite"
    monkeypatch.setattr(
        os, "fsync", lambda descriptor: (_ for _ in ()).throw(OSError("sync failure"))
    )
    with pytest.raises(OSError):
        initialize_journal(journal)
    assert journal.is_file()
    with pytest.raises(FileExistsError):
        initialize_journal(journal)


def test_concurrent_initializers_create_exactly_one_generation(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    tmp_path.chmod(0o700)
    journal = tmp_path / "journal.sqlite"

    def attempt():
        try:
            return initialize_journal(journal)
        except FileExistsError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(lambda _: attempt(), range(2)))
    generations = [value for value in values if value is not None]
    assert len(generations) == 1
    with closing(sqlite3.connect(journal)) as connection:
        assert connection.execute("SELECT journal_id FROM journal_meta").fetchall() == [
            (generations[0],)
        ]


@respx.mock
async def test_unexpected_intent_serialization_error_is_generic_and_blocks_backend(
    authority, monkeypatch
):
    from mcp_unifi import authority as authority_module

    operation = Operation("alice", "serialize_probe", {})
    grant(authority, operation)

    def fail(value):
        raise ValueError("synthetic serialization secret")

    monkeypatch.setattr(authority_module, "scrub", fail)
    client = UniFiClient("gateway.test", "synthetic")
    CLIENTS[client._client] = Target(authority, "home", "default")
    route = respx.post("https://gateway.test:443/proxy/network/api/s/default/rest/wlanconf").mock(
        return_value=httpx.Response(200, json={"data": [{"_id": "new"}]})
    )
    token = OPERATION.set(operation)
    try:
        with pytest.raises(UniFiError, match="Durable prewrite") as caught:
            await client.create_wlan({"name": "first"})
        assert "synthetic serialization secret" not in str(caught.value)
        assert route.call_count == 0
        assert authority.healthy is False
        assert not operation.attempts
        with closing(sqlite3.connect(authority.journal)) as connection:
            assert connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
    finally:
        OPERATION.reset(token)
        await client.aclose()
