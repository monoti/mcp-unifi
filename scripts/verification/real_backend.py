from __future__ import annotations

import argparse
import asyncio
import http.server
import json
import os
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastmcp import Client
from fastmcp.client.transports import StdioTransport


def mint_certificate(directory: Path) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_file = directory / "controller.pem"
    key_file = directory / "synthetic-controller-key.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_file.chmod(0o600)
    return cert_file, key_file


class MockController(http.server.ThreadingHTTPServer):
    def __init__(self, cert: Path, key: Path):
        self.mutations: list[dict[str, object]] = []
        self.reads = 0
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return None

            def respond(self, data):
                body = json.dumps({"meta": {"rc": "ok"}, "data": data}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                owner.reads += 1
                self.respond(
                    [{"_id": "synthetic-wlan", "name": "synthetic-ssid", "enabled": True}]
                    if self.path.endswith("/rest/wlanconf")
                    else [{"mac": "aa:bb:cc:00:00:01", "hostname": "synthetic-client"}]
                )

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                owner.mutations.append({"method": "POST", "path": self.path, "body": body})
                self.respond([{"mac": body.get("mac"), "blocked": True}])

            def do_DELETE(self):
                owner.mutations.append({"method": "DELETE", "path": self.path})
                self.respond([])

        super().__init__(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        self.socket = context.wrap_socket(self.socket, server_side=True)
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.shutdown()
        self.server_close()
        self.thread.join(timeout=5)


def denied(result) -> bool:
    return result.is_error or "error" in json.dumps(result.data).lower()


async def approve(scratch, env, principal, tool, arguments):
    argument_file = scratch / "approval-arguments.json"
    argument_file.write_text(json.dumps(arguments))
    argument_file.chmod(0o600)
    command = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "mcp_unifi.cli.approve",
        "--principal",
        principal,
        "--controller",
        "home",
        "--tool",
        tool,
        "--arguments-file",
        str(argument_file),
        cwd=scratch,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(command.communicate(), timeout=30)
        assert command.returncode == 0, f"approval command failed: {stderr.decode()}"
    finally:
        if command.returncode is None:
            command.kill()
            await command.wait()


async def check_http(scratch, env, config, cert, key, controller):
    away = MockController(cert, key)
    controllers = json.loads(config.read_text())
    controllers.append(
        {
            "name": "away",
            "host": "127.0.0.1",
            "port": away.server_port,
            "site": "away",
            "api_key": "synthetic-away-api-key",
            "verify_ssl": True,
            "pinned_cert": str(cert),
        }
    )
    config.write_text(json.dumps(controllers))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = dict(
        env,
        MCP_TRANSPORT="streamable-http",
        MCP_HOST="127.0.0.1",
        MCP_PORT=str(port),
        MCP_UNIFI_DEFAULT_CONTROLLER="home",
        MCP_UNIFI_AUTH_TOKENS="alice:synthetic-alice-token:network,bob:synthetic-bob-token:network",
    )
    url = f"http://127.0.0.1:{port}"
    before = len(controller.mutations)
    try:
        with (scratch / "http.log").open("w") as logs:
            process = subprocess.Popen(
                [sys.executable, "-m", "mcp_unifi.server"],
                cwd=scratch,
                env=env,
                stdout=logs,
                stderr=logs,
            )
            try:
                async with httpx.AsyncClient() as web:
                    for _ in range(100):
                        assert process.poll() is None, "HTTP subprocess exited"
                        try:
                            response = await web.get(url + "/ready")
                            if response.status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        await asyncio.sleep(0.1)
                    else:
                        raise AssertionError("Writable HTTP readiness did not pass")
                async with (
                    Client(url + "/mcp", auth="synthetic-alice-token") as alice,
                    Client(url + "/mcp", auth="synthetic-bob-token") as bob,
                ):
                    excluded = await alice.call_tool(
                        "list_clients", {"controller": "away"}, raise_on_error=False
                    )
                    assert denied(excluded) and away.reads == 0
                    arguments = {"mac": "aa:bb:cc:00:00:02"}
                    await approve(scratch, env, "alice", "block_client", arguments)
                    wrong_owner = await bob.call_tool(
                        "block_client", arguments, raise_on_error=False
                    )
                    assert denied(wrong_owner) and len(controller.mutations) == before
                    exact = await alice.call_tool("block_client", arguments, raise_on_error=False)
                    assert not denied(exact) and len(controller.mutations) == before + 1
                    deletion = {"wlan_id": "synthetic-wlan"}
                    preview = await alice.call_tool("delete_wlan", deletion)
                    assert not denied(preview)
                    data = (
                        json.loads(preview.data) if isinstance(preview.data, str) else preview.data
                    )
                    token = data["token"]
                    await approve(scratch, env, "alice", "delete_wlan", deletion)
                    stolen = await bob.call_tool(
                        "confirm_destructive_action", {"token": token}, raise_on_error=False
                    )
                    assert denied(stolen) and len(controller.mutations) == before + 1
                    confirmed = await alice.call_tool(
                        "confirm_destructive_action", {"token": token}, raise_on_error=False
                    )
                    assert not denied(confirmed), "owner confirmation could not use original grant"
                    assert len(controller.mutations) == before + 2
                    assert controller.mutations[-1]["method"] == "DELETE"
                    consumed = await alice.call_tool(
                        "confirm_destructive_action", {"token": token}, raise_on_error=False
                    )
                    assert denied(consumed) and len(controller.mutations) == before + 2
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
    finally:
        away.close()
    return {
        "writable_readiness": True,
        "cross_principal_grant_denied": True,
        "excluded_controller_requests": 0,
        "cross_principal_confirmation_denied": True,
        "owner_confirmation_succeeded": True,
        "confirmation_replay_denied": True,
        "approved_http_mutations": len(controller.mutations) - before,
    }


async def probe(repo: Path, output: Path):
    results = {}
    with tempfile.TemporaryDirectory(prefix="unifi-real-boundary-") as temporary:
        scratch = Path(temporary)
        scratch.chmod(0o700)
        grants = scratch / "grants"
        grants.mkdir(mode=0o700)
        cert, key = mint_certificate(scratch)
        controller = MockController(cert, key)
        try:
            config = scratch / "controllers.json"
            config.write_text(
                json.dumps(
                    [
                        {
                            "name": "home",
                            "host": "127.0.0.1",
                            "port": controller.server_port,
                            "site": "default",
                            "api_key": "synthetic-api-key",
                            "verify_ssl": True,
                            "pinned_cert": str(cert),
                        }
                    ]
                )
            )
            config.chmod(0o600)
            env = {
                "PATH": os.defpath,
                "PYTHONPATH": str(repo / "src"),
                "STUB_MODE": "false",
                "MCP_UNIFI_READONLY": "false",
                "MCP_UNIFI_MODULES_ENABLED": "network",
                "MCP_UNIFI_CONTROLLERS_FILE": str(config),
                "MCP_UNIFI_CONTROLLER_SCOPES": json.dumps({"alice": ["home"], "bob": ["home"]}),
                "MCP_UNIFI_STDIO_PRINCIPAL": "alice",
                "MCP_UNIFI_APPROVAL_DIR": str(grants),
                "MCP_UNIFI_MUTATION_JOURNAL": str(scratch / "mutations.sqlite3"),
                "MCP_UNIFI_AUDIT_PATH": str(scratch / "audit.jsonl"),
                "MCP_UNIFI_AUDIT_SINK": "file",
                "LOG_LEVEL": "ERROR",
            }
            arguments = {"mac": "aa:bb:cc:00:00:01"}

            with (scratch / "server.log").open("w") as logs:
                transport = StdioTransport(
                    sys.executable,
                    ["-m", "mcp_unifi.server"],
                    env=env,
                    cwd=scratch,
                    log_file=logs,
                )
                async with Client(transport, timeout=15) as client:
                    reads = await client.call_tool("list_clients")
                    assert not reads.is_error and "synthetic-client" in json.dumps(reads.data)
                    refusal = await client.call_tool(
                        "block_client", arguments, raise_on_error=False
                    )
                    assert denied(refusal), "real mutation succeeded without operator grant"
                    assert not controller.mutations, "denied operation reached mock controller"
                    await approve(scratch, env, "alice", "block_client", arguments)
                    write = await client.call_tool("block_client", arguments, raise_on_error=False)
                    assert not denied(write), "exact granted mutation was refused"
                    assert len(controller.mutations) == 1, (
                        "granted operation did not write exactly once"
                    )
                    changed = await client.call_tool(
                        "block_client", {"mac": "aa:bb:cc:00:00:02"}, raise_on_error=False
                    )
                    assert denied(changed), "changed arguments reused exact approval"
                    assert len(controller.mutations) == 1
                restart = StdioTransport(
                    sys.executable,
                    ["-m", "mcp_unifi.server"],
                    env=env,
                    cwd=scratch,
                    log_file=logs,
                )
                async with Client(restart, timeout=15) as client:
                    replay = await client.call_tool("block_client", arguments, raise_on_error=False)
                    assert denied(replay), "approval replay succeeded after server restart"
                    assert len(controller.mutations) == 1
            results["http"] = await check_http(scratch, env, config, cert, key, controller)
            with closing(sqlite3.connect(scratch / "mutations.sqlite3")) as journal:
                outcomes = journal.execute("SELECT outcome FROM attempts").fetchall()
                rows = len(outcomes)
                assert rows == 3, "durable one-use records missing"
                assert all(row[0] == "success" for row in outcomes), "durable completion missing"
            events = [
                json.loads(line) for line in (scratch / "audit.jsonl").read_text().splitlines()
            ]
            assert any(
                event.get("result", {}).get("phase") == "intent"
                for event in events
                if isinstance(event.get("result"), dict)
            ), "prewrite audit intent missing"
            results.update(
                {
                    "verified_controller_tls": True,
                    "read_calls": controller.reads,
                    "unauthorized_mutations": 0,
                    "externally_granted_mutations": len(controller.mutations),
                    "changed_arguments_denied": True,
                    "restart_replay_denied": True,
                    "durable_attempts": rows,
                }
            )
        finally:
            controller.close()
    output.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    asyncio.run(probe(args.repo.resolve(), args.output.resolve()))
