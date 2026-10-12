---
draft: false
title: Claude Desktop (.dxt)
description: One-click install for Claude Desktop via the Desktop Extension bundle.
---

Build a bundle from the reviewed checkout with an installed Python runtime.

```sh
python scripts/build_dxt.py /tmp/mcp-unifi-dxt
```

The builder uses hash-locked build and runtime dependencies and verifies imports, version metadata, and entry points. Package the output directory as a zip with the `.dxt` suffix. Each generated bundle supports the build host platform; native dependency wheels prevent a single bundle from supporting all hosts. The bundle does not include Python itself. No hardened fork release is published.

The extension uses stdio and defaults to read-only access. Configure verified TLS before using a real controller. See [Hardened fork operations](/mcp-unifi/guides/hardening/) for external grants and migration.
