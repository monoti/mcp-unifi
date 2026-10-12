---
draft: false
title: uvx / pipx
description: Run mcp-unifi straight from the GitHub repo with no install footprint.
---

Use a reviewed local checkout rather than an upstream package. Install hash-locked dependencies before project installation.

```sh
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements-build.lock -r requirements.lock
.venv/bin/pip install --no-deps --no-build-isolation .
STUB_MODE=true .venv/bin/mcp-unifi
```

The server defaults to stdio, read-only tools, and verified TLS. Point the MCP client's command at the installed executable. The fork has not published a package. See [Hardened fork operations](/mcp-unifi/guides/hardening/) for real-controller configuration and external write approvals.
