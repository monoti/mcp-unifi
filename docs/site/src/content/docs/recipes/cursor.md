---
draft: false
title: Cursor
description: Run the installed hardened checkout over stdio.
---

Install this checkout using the [hash-locked installation guide](../guides/hardening.md#read-only-setup). This fork has no published package or DXT release. Upstream install commands do not include these security changes.

Edit `.cursor/mcp.json` for a project or `~/.cursor/mcp.json` for your user. Replace the command with the absolute path to your installed checkout's `.venv/bin/mcp-unifi`. On Windows, use the absolute `.venv/Scripts/mcp-unifi.exe` path.

```json
{
  "mcpServers": {
    "unifi": {
      "command": "/absolute/path/to/mcp-unifi/.venv/bin/mcp-unifi",
      "env": {
        "MCP_TRANSPORT": "stdio",
        "STUB_MODE": "false",
        "MCP_UNIFI_READONLY": "true",
        "UNIFI_HOST": "gateway.example.test",
        "UNIFI_API_KEY_FILE": "/protected/secrets/unifi-api-key",
        "UNIFI_VERIFY_SSL": "true",
        "MCP_UNIFI_AUDIT_SINK": "file",
        "MCP_UNIFI_AUDIT_PATH": "/protected/state/audit.jsonl"
      }
    }
  }
}
```

Store the controller API key in the protected file outside the repository and client configuration. Configure a trusted CA or an independently verified certificate pin when the controller certificate requires it. Keep TLS verification enabled. Use `STUB_MODE=true` to try synthetic tools without a controller.

Fully quit and restart Cursor after editing configuration. Start a conversation and request a read such as listing devices. For writable mode, follow [external approval and journal setup](../guides/hardening.md#approving-a-real-mutation). Keep the approving operator's command and files inaccessible to the caller's other tools.
