# Sol adversarial security review, round 5

## Scope and method

Reviewed the frozen `network/mcp-unifi` commit `44a48fba74cdf415357e62162849c4deb05c40b9` against the verified upstream commit `b9870c768362d5e5b1321c7048a9fc7c035a9c59`, the original security and engineering brief, selected designs, all round-two through round-four findings and triage, and the fifth-round verification record. Traced approval issuance, journal initialization and recovery, scope resolution, confirmation ownership, audit completion, backend request admission, secret emission, and the deployment and release evidence. This was a read-only source and artifact review; no controller was contacted and no source was changed.

## Findings

No findings.

The previously unsafe missing-journal path no longer creates state during server or issuer operation: `Authority._connection()` opens existing SQLite state with `mode=rw`, validates the exact schema and generation, and pins file identity. `begin()` rechecks live storage for cached composite continuations, consumes an unused exact grant and persists sanitized intent before backend I/O. `_record_outcome()` requires exactly one pending row; storage failures poison the authority. `request_with_retry()` calls the common `before_request()` guard for Network, Protect, and Access clients. The exposed tools examined resolve one controller per operation, so the completion wrapper's repeated-owner concern does not have a reachable multi-target call chain in this source.

The authority, journal and request guard remain in one 432-line module with a small public interface. The changed production files did not cross the 1,000-line quality threshold, and I found no concrete simplification that would remove an authorization state or branch without weakening the selected invariants. The 977-line operator test file is large but remains below that threshold and exercises behavior around failure and recovery.

## Attention: decision trail audit

No flags. The append-only trail's rows 48, 50, and 52-57 map the round-four defects, selected recovery design, integrated source, completed fifth-round checks, bounded installed-package audit, pending publication, and explicit raw-log whitespace exception to retained artifacts. In the specified run transcript, the first two package-audit attempts lacked the tool; the later isolated-tool result is present. `desktop-packages-final-r5-tool.log` reports no known vulnerabilities; the trail accurately states that 71 third-party dependencies were checked and the unpublished fork package was skipped. The full-suite log ends with 1,400 passes and 89.42 percent coverage. The final real-backend JSON records zero unauthorized mutations, four externally granted mutations, and four durable attempts. The final Darwin bundle record binds the tested archive to this commit and its scanned bytes. These are local and synthetic results, not evidence of live controller behavior or remote publication.

## Verification limits

I did not reproduce the full suite or the MCP probes independently. No live firmware, actual operator isolation from model-accessible tools, physical power loss, hostile rollback of journal and grants, Docker or Kubernetes runtime storage, desktop application installation, Windows/Linux bundle execution, TLS interception, or remote release was verified here. Publication remains pending.
