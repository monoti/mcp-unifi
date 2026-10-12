---
title: Hardened fork operations
description: Safe defaults, external approvals, storage, and migration.
---

This fork defaults to stdio, read-only tools, and verified controller TLS. The fork has not published an image or Registry entry. Build this checkout instead of pulling an upstream image. Historical upstream installation and firmware claims do not verify this fork.

## Read-only setup

Install the hash-locked build and runtime dependencies in an isolated environment, then install the project without dependency resolution.

```sh
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements-build.lock -r requirements.lock
.venv/bin/pip install --no-deps --no-build-isolation .
STUB_MODE=true .venv/bin/mcp-unifi
```

Configure real controller credentials through protected file-backed secrets outside the repository. Configure a trusted CA or a certificate pin verified through an independent channel. Inline and file-backed credentials both default to TLS verification. Access uses its own certificate pin. Explicitly disabling verification remains an operator configuration choice.

For HTTP, set `MCP_TRANSPORT=streamable-http`. The host defaults to loopback. Keep authentication enabled, use distinct named bearer-token identities, and place remote access behind a trusted TLS proxy. Controller scopes apply to reads and writes when configured. An excluded controller is absent from discovery and cannot be selected through its alias.

## Approving a real mutation

Enabling the write catalog does not authorize a controller request. For a local deployment with a file audit log, configure these settings.

| Setting | Purpose |
| --- | --- |
| `MCP_UNIFI_READONLY=false` | Expose write tools. |
| `MCP_UNIFI_CONTROLLER_SCOPES={"alice":["home"]}` | Explicit controller access for the trusted principal. |
| `MCP_UNIFI_STDIO_PRINCIPAL=alice` | Local stdio identity. HTTP uses the authenticated token identity. |
| `MCP_UNIFI_APPROVAL_DIR=/protected/approvals` | Operator-issued grant files. |
| `MCP_UNIFI_MUTATION_JOURNAL=/protected/state/mutations.sqlite` | Durable one-use journal. |
| `MCP_UNIFI_AUDIT_SINK=file` | Additional sanitized file audit log. |
| `MCP_UNIFI_AUDIT_PATH=/protected/state/audit.jsonl` | Audit file outside the read-only application filesystem. |

Before starting a writable server or issuing an approval, provision the private state directory for the service UID. Initialize the configured absent journal path with the installed checkout's operator command.

```sh
/absolute/path/to/mcp-unifi/.venv/bin/mcp-unifi-journal init \
  --path /protected/state/mutations.sqlite
```

Only this command creates journal state. It refuses any existing path, including symlinks. It commits schema version 2 and a random journal generation, then syncs the file and parent directory. An initialization failure leaves the existing file for operator inspection. Server readiness and approval issuance open existing state only and never create or repair it.

Run the approval CLI outside the model's tool environment. Use the same controller, site, modules, and scope configuration as the server. Place the exact original tool arguments in a protected JSON file. Secrets participate in the digest before redaction.

```sh
/absolute/path/to/mcp-unifi/.venv/bin/mcp-unifi-approve --principal alice --controller home --tool block_client \
  --arguments-file /protected/operator/block-client.json --ttl 300
```

The CLI prints the grant filename. It does not contact a controller. The default lifetime is five minutes and the maximum is one hour. Default arguments are normalized by the registered tool signature. The version 2 grant binds the journal generation, identity, resolved controller, configured site, original tool, and complete arguments. Changing any bound value requires a new approval. A destructive preview token belongs to its issuer. Approval names the original destructive tool, such as `delete_wlan`, rather than `confirm_destructive_action`.

A grant permits one top-level invocation, including its constituent requests and compensation. It is consumed durably before the first request and stays consumed across process restarts or uncertain outcomes. The SQLite row also stores the sanitized original intent as the durable prewrite audit record. The journal uses synchronous EXTRA, requests fullfsync on macOS, and syncs the parent directory after initialization. Audit preparation failure prevents execution. A missing or replaced journal, malformed schema or generation, or a missing pending completion row makes the authority permanently unhealthy for that process. Every constituent controller request checks live journal identity and pending consumption. Completion audit failure or cancellation marks the authority unhealthy and blocks later writes. The server attempts to persist an uncertain outcome without waiting on the failed sink again. Inspect the journal and controller state before issuing a replacement grant after an uncertain outcome. A fresh identical approval can be used even while older consumed grant files remain. Replay and rollback require their own approved original invocation.

## Filesystem ownership and deployment

Grant directories must be owned by the server's effective UID with mode `0700`. Grant files must be owned by that UID with mode `0600`. Journal parent directories and audit private directories require the same owner-only permissions. Symlinks and group or other permission bits are rejected. The operator CLI must run with that ownership, or a trusted administrator must provision grant files for the service UID. Mount grants read-only into the service. Keep the grant writer and approval CLI inaccessible to the model's shell and tools.

Compose builds `mcp-unifi:0.25.0` locally and publishes HTTP on loopback. The default service UID/GID is `1000`. A new named audit volume inherits the image directory ownership. When overriding `MCP_UID`/`MCP_GID`, pre-provision the audit volume for that UID and verify its private child directory is `0700`. Do not assume existing root-owned volumes will become writable. Supply bearer credentials using a protected file or secret mount, then run `docker compose up --build` after reviewing local configuration.

The Helm chart uses `fsGroup` only for ephemeral read-only storage. Persistent claims require operator-provisioned ownership and omit `fsGroup` so Kubernetes cannot rewrite protected grant or journal permissions. Writable Helm mode requires one replica, an audit claim, a read-only approval claim, and explicit controller scopes. Provision both claim roots for the configured service UID before mounting. Do not configure `fsGroup` for persistent claims. Use a durable local filesystem with SQLite locking and directory fsync semantics. These settings depend on the filesystem and storage honoring sync requests. Network filesystems and multiple write replicas are unsupported.

`/health` reports process liveness. `/ready` checks the audit sink and authority storage, and returns `503` when unsafe to serve. Readiness does not prove controller firmware compatibility or API permissions. Docker runtime and live Kubernetes volume behavior have not been verified in this hardening task.

## Recover missing or replaced journal state

Stop every writable server and approval issuer before recovery. Privately preserve the prior journal, SQLite sidecar files, grant files, and audit history with owner-only permissions. Do not delete history to make an existing path pass initialization. Inspect pending or uncertain operations and actual controller outcomes before approving a replacement operation.

Select an absent protected journal path, or move the preserved state away from the configured path while all writers remain stopped. Run `mcp-unifi-journal init` explicitly to create a new generation. Update server and issuer configuration together if the path changes. Restart servers, verify readiness, and issue fresh version 2 grants for operations you still intend.

All version 1 grants are rejected. There is no automatic migration, archival, or recovery command. A preserved version 1 journal requires the same stopped-writer preservation and explicit new-generation procedure. Old version 2 grants remain invalid against a new generation even when unexpired. Recovery does not establish the outcome of a previous controller request or clear its uncertainty.

The server pins device, inode, and generation after its first successful open. Once it observes a storage integrity failure, restoring a file does not restore write health without restarting the process. These checks detect accidental state loss and replacement. They do not defend against privileged rollback of both journal and grants, or prove durability under physical power loss.

## Packaging and migration

All enabled release publication channels wait for tests, lint, strict types, and filesystem/image scans of the exact triggering revision. The release job scans the assembled DXT bundle for high and critical vulnerabilities and secrets before archiving and attaching those files. Registry publication is disabled until fork credentials and ownership are configured. No fork release has been published by this task.

Build a DXT from this checkout with `python scripts/build_dxt.py /new/bundle`. The builder installs hash-locked build and runtime dependencies, then installs the project with `--no-deps --no-build-isolation`. It verifies bundle imports, version metadata, and entry points. Each generated bundle supports the build host's platform because dependencies contain native wheels. Python must already be installed on the target host.

Existing writable deployments must add explicit identity, scopes, protected grant storage, and durable journal/audit paths. Existing self-signed TLS deployments must configure a verified pin or trusted CA. Existing HTTP clients must select HTTP explicitly. Stdio audit output must use a file rather than stdout. Error and backup responses no longer include raw controller diagnostics or opaque backup bytes. Structured domain-error returns are recorded as failed calls.
