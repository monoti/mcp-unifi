---
draft: false
title: Helm
description: Kubernetes deployment via the published Helm chart.
---

Build the local fork image and make that exact image available to the target cluster. Render the local chart before deployment.

```sh
helm lint charts/mcp-unifi
helm template unifi charts/mcp-unifi --set unifi.stubMode=true
```

The chart defaults to read-only tools, verified controller TLS, bearer authentication, and audit-aware readiness. Configure credentials through an existing protected Secret. Writable mode requires a persistent audit claim, a read-only approval claim, explicit controller scopes, and one replica. Provision persistent claims for the service UID without fsGroup rewriting. See [Hardened fork operations](/mcp-unifi/guides/hardening/) for ownership and grant requirements. Live cluster startup and persistent volume behavior remain unverified.
