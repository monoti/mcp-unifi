---
draft: false
title: Docker
description: Run mcp-unifi as a long-running container with Streamable HTTP transport.
---

Build the reviewed fork locally. No fork image has been published.

```sh
docker build -t mcp-unifi:0.25.0 .
```

Use the repository Compose configuration for loopback HTTP, authenticated access, a read-only root filesystem, and dedicated audit storage. Review protected credential mounts and service UID ownership before startup. See [Hardened fork operations](/mcp-unifi/guides/hardening/) for the storage contract and migration instructions. Docker runtime startup was not verified in this hardening task.
