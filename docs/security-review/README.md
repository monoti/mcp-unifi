# Hardening verification record

This fork repairs the Pete findings in the supplied UniFi MCP comparison and security engineering reports. The assessed upstream revision was `b9870c768362d5e5b1321c7048a9fc7c035a9c59`. Findings about Sirkirby's separate server are outside this fork.

Read [the finding map](../security-findings.md) for each repair and [the operator guide](../hardening-operations.md) before enabling writes. The full investigation and candidate designs remain in the local homelab audit directory, `.audit/unifi-hardening/`. The selected design uses an operator file grant, trusted caller identity, the original effective request, and a durable SQLite transaction before each real controller mutation. Secret values participate in the approval digest before redaction.

The design comparison selected the request guard immediately before backend I/O. It adopted caller-owned pending actions, audit health and readiness, and separate Access trust. A separate approval daemon and model-supplied approval arguments added operational complexity without the required benefit for this local deployment. Preview tokens alone do not authorize controller writes.

Journal recovery adds version 2 approvals bound to an explicitly initialized generation. Server and issuer opens never recreate missing storage. Each continuation checks the live journal, and completion requires exactly one pending row. Read [the selected approval design](history/selected-design.md) and [the journal recovery design](history/journal-selected-design.md) for the contracts and rejected alternatives.

## Original verified checkpoint

[The revision record](verified-revision.json) names the source commit for the results below. Follow-up changes standardize the local image name as `mcp-unifi`, keep audit artifacts local, restore environment guidance, and refresh dependency locks. Rerun the checks with the current locks before reusing these results for a newer revision.

| Check | Observed result | Evidence |
| --- | --- | --- |
| Complete pytest suite | 1400 passed, five existing warnings, 89.42 percent coverage. | [Raw suite output](evidence/full-suite.log). |
| Actual stdio and HTTP MCP | 74 stdio tools, reads across three products, write refusal, authenticated scoped HTTP. | [Protocol results](evidence/protocol.json). |
| Real HTTPS transport to isolated simulator | Zero unauthorized writes, four approved writes, four durable records, caller and replay refusal. | [Backend results](evidence/real-backend.json). |
| Secret diagnostics | All eight leakage flags false. | [Diagnostics results](evidence/diagnostics.json). |
| Darwin desktop artifact | Bundled MCP negotiation and reads passed; archive CRC and exact bundle bytes verified. | [Artifact results and checksum](evidence/desktop.json). |
| Installed package advisories | 71 third-party packages audited with zero advisories; unpublished fork package skipped. | [Package audit](evidence/desktop-packages.json). |
| Trivy assembled artifact scan | 72 installed packages detected; zero configured high or critical vulnerability or secret matches. | [Scanner output](evidence/desktop-trivy.json). |

Ruff, mypy on 67 source files, actionlint, and the 160-page docs build also passed. Astro telemetry was disabled for the docs build because its preferences path is outside the restricted workspace. These results establish local behavior at the recorded revision.

## Independent review and preserved decisions

The final independent reviewers reported no new implementation findings. Read [Sol's final review](history/security-review-sol-r5.md), [Luna's final review](history/security-review-luna-r5.md), [Terra's final review](history/security-review-terra-r5.md), and [the parent triage](history/security-triage-r5.md). All prior reviews, accepted findings, responses, and selected design alternatives remain in [the history directory](history/).

[The decision trail](decisions.tsv) preserves failed checks and later corrections at the original checkpoint. Its two raw failing-test logs remain in the local audit directory with their original pytest whitespace. Audit artifacts are ignored and excluded from the current Git tree. The initial failed review dispatches supplied no verdict. The earlier failed scanner download supplied no scan result; successful later scans close that check.

The complete private working record remains in the local homelab audit directory. Private transcripts and credentials are excluded from this publication.

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
