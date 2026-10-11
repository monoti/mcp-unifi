# Independent security review, round 5

Reviewed `network/mcp-unifi` at `44a48fba74cdf415357e62162849c4deb05c40b9` against upstream `b9870c768362d5e5b1321c7048a9fc7c035a9c59`. I read the complete shared review prompt, prior accepted findings and responses, journal design alternatives, implementation and recovery reports, the full changed-file inventory, and the relevant authority, request, confirmation, scope, audit, CLI, packaging, and deployment paths. I also inspected the specified decision trail and selectively parsed the specified run transcript. This review was read-only apart from this report; I did not contact controllers, use credentials, run tests, or change source.

## Findings

No findings.

The prior grant-shadowing, cancellation, queued-admission, schema-default, setup-guidance, and journal-loss findings are addressed in the inspected call paths and artifacts. `Authority.begin()` chooses and consumes an unused matching grant in the transaction, checks health after awaited audit preparation, and verifies live journal identity on continuations. Completion requires exactly one pending row; the audited wrapper makes the authority unhealthy on interrupted or failed completion. The external initializer and version-2 generation binding prevent server or issuer startup from recreating missing history or accepting an old grant after reinitialization. The release workflow scans the assembled DXT before archiving it, and current fork setup guidance points to local hardened installation instructions.

## Attention: decision-trail audit

- **Transcript ordinal 3267; trail rows 52–56:** The final `git diff --check b9870c768362d5e5b1321c7048a9fc7c035a9c59 HEAD` exited 2. It reports trailing whitespace in preserved pytest evidence under `.audit/final-boundaries/red.log` and `.audit/review-fixes/red.log`, plus `tests/test_operator_grants.py:408`. The current TSV tail records the successful suite, scans, package audit, and pending publication, but does not record this failed final check. It is a hygiene failure rather than evidence of a runtime defect; record it as such so a reader does not infer every final check passed. The package audit, initially described as running in the prompt, subsequently completed: the transcript and row 55 report 71 third-party packages with no advisories and explicitly skip unpublished `mcp-unifi`.
- **Publication boundary:** Row 56 and the transcript say a PR tool was selected but no push or PR occurred. The pending status is accurate; this review does not establish or authorize publication.

## Verification limits

No live controller firmware or privilege compatibility, actual TLS interception, Docker or Kubernetes runtime, desktop installation, Windows/Linux artifact execution, physical power-loss behavior, remote release workflow, merge, or deployment was verified. The synthetic probes and host-specific Darwin artifact checks remain bounded evidence.
