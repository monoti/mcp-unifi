# Hardening verification record

This fork repairs the Pete findings in the supplied UniFi MCP comparison and security engineering reports. The assessed upstream revision was `b9870c768362d5e5b1321c7048a9fc7c035a9c59`. Findings about Sirkirby's separate server are outside this fork.

Read [the finding map](../security-findings.md) for each repair and [the operator guide](../hardening-operations.md) before enabling writes. The full investigation and candidate designs remain in the local homelab audit directory, `.audit/unifi-hardening/`. The selected design uses an operator file grant, trusted caller identity, the original effective request, and a durable SQLite transaction before each real controller mutation. Secret values participate in the approval digest before redaction.

The design comparison selected the request guard immediately before backend I/O. It adopted caller-owned pending actions, audit health and readiness, and separate Access trust. A separate approval daemon and model-supplied approval arguments added operational complexity without the required benefit for this local deployment. Preview tokens alone do not authorize controller writes.

## Rerun the protocol checks

Use Python 3.13 and install the hash-locked development dependencies in an isolated virtual environment. Run these commands from the repository root. Output files contain synthetic test results.

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
mkdir -p /tmp/unifi-hardening-results
.venv/bin/python scripts/verification/diagnostics.py . > /tmp/unifi-hardening-results/diagnostics.json
.venv/bin/python scripts/verification/protocol.py . /tmp/unifi-hardening-results/protocol.json
.venv/bin/python scripts/verification/real_backend.py . /tmp/unifi-hardening-results/real-backend.json
```

The probes launch the actual MCP server in temporary directories with a minimal environment. They do not inherit `.env`, controller settings, or credentials. The protocol probe checks default stdio reads across Network, Protect, and Access, authenticated loopback HTTP, hidden write refusal, and module scopes. The backend probe starts an isolated HTTPS controller simulator and uses real HTTP transport. It verifies approved execution, unauthorized refusal before backend I/O, changed arguments, restart replay, HTTP caller ownership, pending confirmation ownership, controller scopes, and durable outcomes. It uses the actual operator approval CLI outside MCP.

The diagnostics probe checks formatted structured logger arguments, serialized JSON, exception causes, unexpected domain messages, and audit error text. Each probe fails on a violated assertion. Allow isolated loopback listeners when running in a restricted execution environment.

## Evidence limits

Synthetic tests and source review do not establish compatibility with live UniFi firmware or account privileges. No production controller was contacted. Docker and Kubernetes runtime behavior remain unverified. Helm rendering and Compose validation check configuration, rather than mounted storage ownership or container startup. The desktop bundle was built for the build host; it is not a universal platform bundle.

Approval depends on an independent operator. A model that also has the approving operator's shell or writable approval directory can mint its own grants. Restrict that access outside this MCP server. Durable storage must honor file sync and SQLite locking, and the grant and journal directories must retain the documented private permissions.
