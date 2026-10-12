# Terra adversarial security review, r5

## Findings

No findings.

I reviewed the frozen `network/mcp-unifi` source at
`44a48fba74cdf415357e62162849c4deb05c40b9` against
`b9870c768362d5e5b1321c7048a9fc7c035a9c59`. Both revisions resolve as
commits. The review covered the full diff and surrounding authority, journal
initialization and issuance, request-hook, audit lifecycle, pending
confirmation, scope, deployment, documentation, packaging, and release paths.
I also read the requested design, recovery, implementation, comment-review,
round-2 through round-4 review and triage, and journal-design records.

The prior accepted findings are closed in the current implementation rather
than merely described as closed. Normal server and issuer opens use
non-creating SQLite access and validate the exact schema plus singleton v2
generation. `Authority.begin()` validates live state before both fresh and
cached continuations, atomically consumes a matching unused v2 generation-bound
grant with durable pending intent before a real client request, and rechecks
health after its only awaited admission step. Completion requires exactly one
pending row and poisons write health on failure. The external initializer alone
creates state at an absent protected path. The request hook remains the common
real-client mutation boundary, while the only mock-transport exemption is a
test transport and retains read-only/scope enforcement. Confirmation restores
the original immutable operation context after issuer and current scope checks.

The current documentation and deployment defaults consistently keep writes
disabled until the separate identity, scope, grants, initialized journal, and
audit storage are supplied. The retained limits are appropriately bounded:
local SQLite/filesystem semantics, privileged rollback, live controller
compatibility and permissions, container/Kubernetes mounted storage, physical
power loss, desktop installation, and remote publication were not established
by this source review.

## Attention: decision-trail audit

No flags. Trail rows 52--57 map the selected recovery design, frozen
implementation revision, complete r5 suite/protocol/artifact checks, the final
package audit, and the still-pending publication state to concrete artifacts.
The specified transcript records the final package-audit tool result and the
explicit preservation of raw failing-test whitespace; it does not convert the
earlier failed Trivy download attempts into evidence, and later rows correctly
record the successful replacement scans. Neither the trail nor transcript
claims deployment, release publication, or live-controller validation.

## Review limits

This was a read-only review. I did not run tests, contact a controller, access
credentials, build or install artifacts, start Docker or Kubernetes, publish,
or modify the frozen checkout.
