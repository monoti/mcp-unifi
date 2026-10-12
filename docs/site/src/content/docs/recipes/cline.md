---
draft: false
title: Cline
description: Wire mcp-unifi into Cline (VS Code MCP client).
---

This page retains upstream reference material. For this fork, follow [Hardened fork operations](/mcp-unifi/guides/hardening/). Build the checkout locally. No fork image or Registry entry has been published. Read-only, stdio, and verified TLS are the defaults; real writes need external operator grants.


Cline reads MCP server config from the VS Code settings UI (Cline → MCP Servers) or directly from `cline_mcp_settings.json`.

## Streamable HTTP (Docker)

Start the container. The HTTP transport is secure by default and refuses to start without a bearer token, so mint one first:

```bash
export MCP_UNIFI_TOKEN=$(openssl rand -hex 32)
docker run -d --rm -p 127.0.0.1:3714:3714 \
  -e MCP_TRANSPORT=streamable-http \
  -e MCP_HOST=0.0.0.0 \
  -e STUB_MODE=true \
  -e MCP_UNIFI_AUTH_TOKENS="$MCP_UNIFI_TOKEN" \
  --name mcp-unifi mcp-unifi:0.25.0
```

Add to `cline_mcp_settings.json`, passing the same token as an `Authorization` header:

```json
{
  "mcpServers": {
    "unifi": {
      "transport": "streamable-http",
      "url": "http://localhost:3714/mcp",
      "headers": {
        "Authorization": "Bearer <paste-token-from-openssl-rand-hex-32>"
      },
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

For real mode against a gateway, run the container with `STUB_MODE=false`, `UNIFI_HOST`, and `UNIFI_API_KEY` — Cline's config doesn't change beyond the token header.

Reload the Cline panel after editing the file. The `unifi` server should appear under the MCP Servers list with a green dot.
