---
draft: false
title: Security Model
description: Threat model, hardening, image signing, and supply-chain provenance.
---

Read-only tools, stdio, loopback HTTP binding, and verified controller TLS are the defaults. Real mutations require a trusted caller with explicit controller scope and an operator-issued exact-request grant. Pending destructive confirmations belong to their issuer and preserve the original tool intent. The model cannot mint grants through MCP.

The actual request boundary checks real transports, including composite and compensation requests. A synthetic bypass applies only to the selected `httpx.MockTransport`; there is no production environment switch. Access certificate pins are independent from gateway pins. Excluded controllers are filtered from discovery and cannot be selected through aliases.

SQLite stores the sanitized original intent and consumes the grant before controller I/O. It uses synchronous EXTRA, fullfsync, and parent directory sync. Restart replay is refused. Audit preparation failure prevents execution. Failed completion persistence reports an uncertain outcome, blocks later writes, and fails readiness. Storage durability depends on filesystem sync and locking guarantees.

Controller errors use bounded internal diagnostics or generic messages. Structured logs and audit records scrub secrets. Unknown exception text and chained traceback details do not reach MCP responses. Decoded backups are scrubbed and opaque backup bytes are refused. Complete secret argument values participate in approval digests before redaction.

Grant files require owner-only permissions and a read-only service mount. Keep the grant writer outside the model's shell and tool environment. A compromised operator account or model-accessible approval CLI can bypass this separation. A read-only controller API key remains useful defense in depth.

Release gates require exact-revision tests, lint, types, and scans. Registry publication is disabled and no fork image is published. Source, synthetic tests, actual MCP entry points against isolated HTTPS mocks, and generated bundle imports were verified. Production firmware, controller privilege levels, Docker startup, and live Kubernetes storage remain unverified.

Follow [Hardened fork operations](/mcp-unifi/guides/hardening/) for setup and migration. Configure a trusted CA or independently verified `pinned_cert` with `mcp-unifi-pin-cert` before real controller access.
