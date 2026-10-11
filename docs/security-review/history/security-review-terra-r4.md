# Terra adversarial security review, r4

## Scope and method

Reviewed `network/mcp-unifi` at frozen commit
`cae347af47e96f7fbdad3989065f28404680d827` against upstream
`b9870c768362d5e5b1321c7048a9fc7c035a9c59`, the supplied hardening
contract and prior review/triage records, the full changed surface, and the
surrounding authority, audit, request, scope, confirmation, configuration,
deployment, package, and regression-test paths. I also read the specified
decision trail and selectively inspected the specified run transcript for the
R4 verification sequence. This was a static, read-only review: I did not
contact a controller, access credentials, run Docker or Kubernetes, publish,
or change source.

## Findings

No findings.

The two accepted R3 paths are closed by the current source rather than merely
described as fixed. `Authority.begin()` now rechecks `self.healthy` after the
only awaited admission step and before the synchronous SQLite selection and
commit (`src/mcp_unifi/authority.py:180-240`); the queued-call regression
establishes that B is waiting before A is cancelled and then asserts one
backend request, no B consumption, and readiness failure
(`tests/test_operator_grants.py:499-572`). Stdio validation applies the same
`strip().lower()` normalization used by sink construction
(`src/mcp_unifi/server.py:112-116`, `src/mcp_unifi/audit.py:298-304`).

## Attention

- **Decision-trail row 47 and transcript ordinals 2417 and 2427:** the final
  full-suite result remains pending. `full-suite-final.log` contains collection
  of 1379 tests and partial progress only; it has no pytest terminal summary
  or exit status. The transcript likewise shows progress through 13 percent,
  not completion. This is an evidence gap, but not an overstatement in the
  trail: row 47 explicitly labels the full run pending. Do not attribute a
  full-suite pass to `cae347a` until its completed output is preserved.
- **Transcript ordinals 2415-2428:** the final protocol, real-backend, and
  Darwin-bundle artifacts were completed with synthetic/local inputs and name
  the exact source commit. They support those bounded checks only; they do not
  establish controller compatibility, Docker/Kubernetes mount behavior,
  desktop installation, remote publication, or power-loss durability. This is
  consistent with the recorded verification limits.

## Review limits

This review cannot establish live controller/firmware/account compatibility,
external operator isolation from other caller tools, Docker or Kubernetes
runtime behavior, desktop installation, remote release execution, filesystem
semantics under physical power loss, or publication. Those remain separate
verification obligations.
