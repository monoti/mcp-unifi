from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx
from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def check_reads(client: Client, *, scoped: bool = False) -> dict[str, int]:
    tools = {tool.name for tool in await client.list_tools()}
    expected = {"list_networks"} if scoped else {"list_networks", "list_cameras", "list_doors"}
    assert expected <= tools, f"read discovery omitted {expected - tools}"
    assert "block_client" not in tools, "read-only discovery exposed block_client"
    assert "confirm_destructive_action" not in tools, "read-only discovery exposed confirmation"
    for name in expected:
        result = await client.call_tool(name)
        assert not result.is_error, f"{name} failed"
        assert result.data, f"{name} returned no synthetic inventory"
    clients_before = await client.call_tool("list_clients")
    refused = await client.call_tool(
        "block_client", {"mac": "aa:bb:cc:00:00:01"}, raise_on_error=False
    )
    assert "error" in json.dumps(refused.data).lower(), "direct hidden write was not refused"
    clients = await client.call_tool("list_clients")
    assert clients.data == clients_before.data, "refused write changed state"
    return {"listed_tools": len(tools), "read_calls": len(expected), "refused_writes": 1}


async def main(repo: Path, output: Path) -> None:
    results: dict[str, object] = {"repository": str(repo)}
    with tempfile.TemporaryDirectory(prefix="unifi-protocol-") as scratch:
        env = {
            "PATH": os.defpath,
            "PYTHONPATH": str(repo / "src"),
            "STUB_MODE": "true",
            "MCP_UNIFI_MODULES_ENABLED": "network,protect,access",
            "MCP_UNIFI_AUDIT_PATH": str(Path(scratch) / "audit.jsonl"),
            "MCP_UNIFI_AUDIT_SINK": "file",
            "LOG_LEVEL": "ERROR",
            "LOG_FORMAT": "json",
        }
        defaults = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json; from mcp_unifi.config import Settings; "
                "s=Settings(_env_file=None); "
                "print(json.dumps(dict(readonly=s.readonly,transport=s.mcp_transport,"
                "host=s.mcp_host,verified_tls=s.controllers[0].verify_ssl)))",
            ],
            cwd=scratch,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        results["defaults"] = json.loads(defaults.stdout)
        assert results["defaults"] == {
            "readonly": True,
            "transport": "stdio",
            "host": "127.0.0.1",
            "verified_tls": True,
        }, f"unsafe defaults {results['defaults']}"
        with (Path(scratch) / "stdio-stderr.log").open("w") as logs:
            transport = StdioTransport(
                sys.executable,
                ["-m", "mcp_unifi.server"],
                env=env,
                cwd=scratch,
                log_file=logs,
            )
            async with Client(transport, timeout=15) as client:
                results["stdio"] = await check_reads(client)

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        network_token = secrets.token_urlsafe(32)
        protect_token = secrets.token_urlsafe(32)
        env.update(
            MCP_TRANSPORT="streamable-http",
            MCP_HOST="127.0.0.1",
            MCP_PORT=str(port),
            MCP_UNIFI_AUTH_TOKENS=(
                f"network-probe:{network_token}:network,protect-probe:{protect_token}:protect"
            ),
            MCP_UNIFI_CONTROLLER_SCOPES=json.dumps(
                {"network-probe": ["default"], "protect-probe": ["default"]}
            ),
        )
        with (Path(scratch) / "http-server.log").open("w") as logs:
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
                        assert process.poll() is None, "HTTP server exited during startup"
                        try:
                            ready = await web.get(url + "/health")
                            if ready.status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        await asyncio.sleep(0.1)
                    else:
                        raise AssertionError("HTTP server did not start")
                    unauthenticated = await web.get(url + "/mcp")
                    assert unauthenticated.status_code == 401, "unauthenticated HTTP was accepted"
                    wrong_token = await web.get(
                        url + "/mcp", headers={"Authorization": "Bearer synthetic-wrong-token"}
                    )
                    assert wrong_token.status_code == 401, "unknown HTTP bearer was accepted"
                async with Client(url + "/mcp", auth=network_token, timeout=15) as client:
                    results["http"] = await check_reads(client, scoped=True)
                async with Client(url + "/mcp", auth=protect_token, timeout=15) as client:
                    tools = {tool.name for tool in await client.list_tools()}
                    assert "list_cameras" in tools and "list_networks" not in tools
                    denied = await client.call_tool("list_networks", raise_on_error=False)
                    assert denied.is_error or "error" in json.dumps(denied.data).lower(), (
                        "module scope did not deny"
                    )
                    results["http_authorization"] = {
                        "missing_bearer_status": unauthenticated.status_code,
                        "invalid_bearer_status": wrong_token.status_code,
                        "module_discovery_and_direct_call_denied": True,
                    }
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        events = [
            json.loads(line) for line in (Path(scratch) / "audit.jsonl").read_text().splitlines()
        ]
        assert any(event.get("denied_by") == "readonly" for event in events)
        assert any(event.get("denied_by") == "scope" for event in events)
        results["audit_records"] = len(events)
    output.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    asyncio.run(main(arguments.repo.resolve(), arguments.output.resolve()))
