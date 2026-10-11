# Finding-to-test map

These repairs address the Pete findings in the repository comparison and security engineering reports. Evidence uses synthetic values and isolated resources. Passing checks do not establish firmware compatibility, controller least privilege, or complete security.

| Finding or failure mode | Repair | Regression evidence |
| --- | --- | --- |
| Raw controller errors and chained exceptions disclose credentials. | Bounded internal diagnostics; generic unknown errors; scrubbed JSON and text log formatting. | `tests/test_redaction.py`, `tests/test_client.py`, `tests/protect/test_real_mode.py`, `tests/access/test_real_mode.py`. |
| Audit error fields bypass redaction. | Untrusted errors become fixed diagnostic text; structured arguments and returns are scrubbed. | `tests/test_redaction.py`, `tests/test_audit.py`, `tests/test_audit_integration.py`. |
| Backup bytes or decoded backup credentials escape. | Scrub decoded configuration; refuse opaque backup content. | `tests/network/test_backup_restore.py`, `tests/test_redaction.py`. |
| Writable HTTP and unverified TLS defaults expose authority. | Read-only stdio and loopback defaults; verified TLS for Network, Protect, UniFi OS, and Access. | `tests/test_config.py`, `tests/test_tls_pinning.py`, `tests/test_readonly.py`, `tests/test_auth.py`. |
| Access incorrectly reuses a gateway pin. | Independent Access endpoint certificate configuration. | `tests/access/test_real_mode.py`, `tests/test_tls_pinning.py`. |
| A caller can select an unauthorized controller. | Registry resolves aliases and enforces caller scopes before reads and writes; discovery filters names. | `tests/test_operator_grants.py`, `tests/network/test_console.py`. |
| Model-controlled confirmations authorize real writes. | Actual request boundary requires an externally issued exact grant. | `tests/test_operator_grants.py`, `tests/test_write_execution_gate.py`. |
| Secret argument changes collide after redaction. | Digest complete normalized values before redaction. | `tests/test_operator_grants.py`. |
| Another principal steals a pending confirmation. | Bind token to issuer and original tool intent; reject without consuming. | `tests/test_operator_grants.py`, `tests/network/test_preview_confirm.py`. |
| Grants replay after restart or race between requests. | SQLite primary-key consumption with synchronous EXTRA, fullfsync, and parent directory sync before network access. | `tests/test_operator_grants.py`. |
| Approval expires while audit preparation awaits. | Recheck expiry after durable audit preparation. | `tests/test_operator_grants.py`. |
| Audit or journal failure permits a write or falsely reports success. | Deny prewrite failures; mark completion failure unhealthy and uncertain; readiness returns unavailable. | `tests/test_operator_grants.py`, `tests/test_audit_integration.py`, `tests/test_healthcheck.py`. |
| Synthetic bypass accidentally reaches a real transport. | Bypass only the actual selected `httpx.MockTransport`; no MCP argument or environment bypass. | `tests/test_write_execution_gate.py`, `tests/test_operator_grants.py`. |
| Broad published port, read-only audit filesystem, upstream unsafe image. | Local fork build, loopback publish, dedicated private writable storage, readiness probe. | `tests/test_deployment_security.py`, Compose parse and Helm rendering. |
| Kubernetes fsGroup rewrites owner-only persistent files. | Omit fsGroup for persistent claims and require pre-provisioned service ownership. | `tests/test_deployment_security.py`, writable Helm rendering. |
| Tag publishers bypass tests and scans or cancel each other. | All enabled channels require exact-revision reusable CI; caller-specific concurrency. Registry publication disabled. | `tests/test_deployment_security.py`, actionlint. |
| DXT resolves floating runtime or build dependencies. | Hash-locked runtime and build installation; no-deps/no-build-isolation project build; real bundle import probe. | `scripts/build_dxt.py`, isolated generated bundle. |

The independent protocol probes launched the actual stdio and authenticated HTTP server entry points against an isolated HTTPS mock controller using the normal network transport. They verified reads, zero unauthorized mutations, externally approved mutations, wrong-principal and changed-argument refusal, original-intent confirmation, restart replay refusal, scoped discovery, and writable readiness. They contacted no production controller.

Docker daemon startup, actual persistent Kubernetes volumes, controller firmware, and live API privilege levels remain unverified. Release workflows were linted and rendered locally, not executed as remote publications. The fork has not published a release or Registry entry.
