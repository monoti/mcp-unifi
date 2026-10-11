"""Create an exact, short-lived grant outside the MCP protocol."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, get_type_hints

from fastmcp.tools import FunctionTool
from pydantic import create_model

from mcp_unifi.authority import intent_digest, secure_path
from mcp_unifi.config import Settings
from mcp_unifi.server import build_server


async def create_grant(
    settings: Settings,
    *,
    identity: str,
    controller: str,
    tool_name: str,
    arguments: dict[str, Any],
    ttl: int,
) -> Path:
    if settings.approval_dir is None:
        raise ValueError("Configure MCP_UNIFI_APPROVAL_DIR.")
    secure_path(settings.approval_dir, directory=True)
    controller_config = next(c for c in settings.controllers if c.name == controller)
    if controller not in settings.controller_scopes.get(identity, []):
        raise ValueError("Caller lacks an explicit controller scope.")
    server = build_server(settings.model_copy(update={"stub_mode": True, "readonly": False}))
    tool = await server.get_tool(tool_name)
    if not isinstance(tool, FunctionTool):
        raise ValueError("Approval requires a registered callable tool.")
    signature = inspect.signature(tool.fn)
    hints = get_type_hints(tool.fn, include_extras=True)
    fields: dict[str, Any] = {
        name: (
            hints.get(name, Any),
            parameter.default if parameter.default is not inspect.Parameter.empty else ...,
        )
        for name, parameter in signature.parameters.items()
    }
    model = create_model("ApprovedArguments", **fields)
    normalized = model(**arguments).model_dump(mode="json")
    digest = intent_digest(identity, controller, controller_config.site, tool_name, normalized)
    grant_id = str(uuid.uuid4())
    grant = {
        "version": 1,
        "id": grant_id,
        "principal": identity,
        "controller": controller,
        "site": controller_config.site,
        "digest": digest,
        "expires": time.time() + ttl,
    }
    path = settings.approval_dir / f"{grant_id}.json"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as file:
        json.dump(grant, file, sort_keys=True)
        file.flush()
        os.fsync(file.fileno())
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--principal", required=True)
    parser.add_argument("--controller", required=True)
    parser.add_argument("--tool", required=True)
    parser.add_argument("--arguments-file", required=True, type=Path)
    parser.add_argument("--ttl", type=int, default=300, choices=range(1, 3601))
    arguments = parser.parse_args()
    try:
        path = asyncio.run(
            create_grant(
                Settings(),
                identity=arguments.principal,
                controller=arguments.controller,
                tool_name=arguments.tool,
                arguments=json.loads(arguments.arguments_file.read_text()),
                ttl=arguments.ttl,
            )
        )
    except Exception as exc:
        parser.error(
            f"Approval failed ({type(exc).__name__}). Check protected configuration and arguments."
        )
    print(path)


if __name__ == "__main__":
    main()
