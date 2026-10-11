from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

import httpx
import respx


async def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        root.chmod(0o700)
        legacy = root / "authority.py"
        legacy.write_bytes(
            subprocess.check_output(  # noqa: S603
                [shutil.which("git"), "show", "cae347a:src/mcp_unifi/authority.py"]
            )
        )
        spec = importlib.util.spec_from_file_location("mcp_unifi.authority", legacy)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        from mcp_unifi.clients.unifi import UniFiClient

        grants = root / "grants"
        grants.mkdir(mode=0o700)
        authority = module.Authority(
            readonly=False,
            scopes={"alice": ["home"]},
            grants=grants,
            journal=root / "journal.sqlite",
        )
        operation = module.Operation("alice", "probe", {})
        grant = grants / "grant.json"
        grant.write_text(
            json.dumps(
                {
                    "version": 1,
                    "id": "probe",
                    "principal": "alice",
                    "controller": "home",
                    "site": "default",
                    "digest": module.intent_digest("alice", "home", "default", "probe", {}),
                    "expires": time.time() + 300,
                }
            )
        )
        grant.chmod(0o600)
        client = UniFiClient("gateway.test", "synthetic")
        module.CLIENTS[client._client] = module.Target(authority, "home", "default")
        token = module.OPERATION.set(operation)
        import os

        os.environ["MCP_UNIFI_STDIO_PRINCIPAL"] = "alice"
        try:
            with respx.mock:
                route = respx.post(
                    "https://gateway.test:443/proxy/network/api/s/default/rest/wlanconf"
                ).mock(return_value=httpx.Response(200, json={"data": [{"_id": "new"}]}))
                await client.create_wlan({"name": "first"})
                print(f"authorized first backend effects={route.call_count}")
                authority.journal.unlink()
                await client.create_wlan({"name": "second"})
                print(f"BUG composite after unlink backend effects={route.call_count}")
                authority.complete(operation, "success")
                with closing(sqlite3.connect(authority.journal)) as connection:
                    rows = connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
                    print(f"BUG completion returned success with pending rows={rows}")
                assert route.call_count == 2
        finally:
            module.OPERATION.reset(token)
            await client.aclose()


asyncio.run(main())
