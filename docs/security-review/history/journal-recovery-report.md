# Journal recovery implementation report

The source is frozen at `a01925f5f20ece78a99bc8e188eb124c3f219828` on `harden/journal-recovery` in `network/mcp-unifi-journal-recovery`. The worktree was clean after commit. The parent checkout was not edited. No push, PR, publication, real-controller operation, credential read, full-suite run, Docker startup, or Kubernetes startup was performed.

## Changes and contract reconciliation

`Authority` remains the SQLite owner. `OperatorGrant` accepts version 2 only and requires a 32-character random journal generation. The canonical effective-operation digest remains version 1 because its argument normalization contract did not change; the grant envelope separately binds the journal generation. Every version 1 grant is refused. A stale version 2 grant is a healthy refusal against a newly initialized generation.

The only initialization command is `mcp-unifi-journal init`, optionally taking `--path` or using `MCP_UNIFI_MUTATION_JOURNAL`. Its `initialize_journal` implementation uses exclusive creation and no-follow flags at an absent owner-only path. It creates both tables and singleton version/generation metadata in one immediate transaction, commits, verifies created-file identity, syncs the file, and syncs its parent directory. Failure preserves the existing file for explicit inspection; there is no automatic cleanup, archival, recovery, or migration command.

Server and issuer open existing SQLite state with `mode=rw`. Normal opens execute no DDL and never create a missing journal. They require the exact initialized schema, rejecting additional SQL-defined objects such as triggers, and validate singleton version/generation metadata. They check protected regular-file ownership and permissions, file identity before and after open, and pin device, inode, and generation after the first successful open. An observed storage integrity failure permanently poisons authority health. Restoring a prior file does not authorize more requests in that process.

Every real backend continuation checks live journal storage before trusting `Operation.attempts`. A reused operation also requires its durable grant row to remain pending. Initial consume retains the audit preparation await, immediate post-await health check, expiry checks, `BEGIN IMMEDIATE` unused-grant selection, and sanitized pending commit before backend I/O. Identity and generation checks surround consume and completion transactions. Completion updates exactly one pending row; zero rows or storage failure makes the outcome uncertain and health false. Cancellation keeps synchronous unhealthy marking, best-effort uncertain persistence, and context cleanup from R2/R3. The best-effort recorder shares the same exactly-one pending-row transaction rather than a separate weaker UPDATE.

Expected consumed/expired refusals use a private `_GrantRefused` diagnostic exception. Unexpected serialization `ValueError` remains a generic fail-closed error with no exception text promoted into trusted diagnostics. This is the parent's requested error-boundary reconciliation. The synthetic serialization regression observes zero backend requests, no pending insertion, no secret in the diagnostic, and unhealthy authority.

The operator fixture now invokes the actual initialization CLI in its isolated temporary environment. `scripts/verification/real_backend.py` invokes the actual CLI before server startup or approvals. The DXT builder verifies the new console entry point in installed metadata. The parent owns executing that real backend probe and rebuilding the bundle.

The operator guide and mirrored site guide document initial state setup, stopped writers and issuers, private preservation of journal/sidecar/grant/audit history, actual outcome inspection, explicit new-generation initialization, restart, version 1 rejection, and stale version 2 refusal. README links now target this checkout's manifest, guides, and references. Unsupported published channel claims were removed. Desktop and Cursor recipes use an absolute installed checkout command, hash-locked install instructions, file-backed secret placeholders, read-only defaults, and verified TLS. The Unreleased changelog covers the original security and migration repairs. Two small README corrections remove the stale test count and clarify that the service account has no login shell.

## Reproduction and checks

All Python checks used `/Users/monoti/projects/homelab/network/mcp-unifi/.venv/bin/python` with `PYTHONPATH=src` while working exclusively in the owned worktree.

| Command | Observed result | Preserved evidence |
| --- | --- | --- |
| `python -m pytest tests/test_operator_grants.py -k 'live_journal_loss or deleted_pending_row' --no-cov` before source fixes | Two failures with `DID NOT RAISE UniFiError`; each first performed one observable backend write | `.audit/journal-recovery/red.log` |
| `python .audit/journal-recovery/reproduce_baseline.py` | Loads frozen `cae347a` Authority in an isolated temp directory. Logs one authorized effect, a second backend effect after unlink, and successful completion with zero durable rows | `.audit/journal-recovery/red-backend-effects.log` and reproducible script |
| `python -m pytest tests/test_operator_grants.py tests/test_audit.py tests/test_audit_integration.py tests/test_deployment_security.py tests/test_secret_files.py --no-cov` | 134 passed in 11.38 seconds before the final serialization-boundary refinement | `.audit/journal-recovery/green-final.log` |
| `python -m pytest tests/test_operator_grants.py --no-cov` after final refinement | 45 passed in 8.96 seconds | `.audit/journal-recovery/green-final-authority.log` |
| `python -m ruff check src tests scripts evals .audit/journal-recovery/reproduce_baseline.py` | Exit 0, all checks passed | `.audit/journal-recovery/ruff.log` |
| `python -m ruff format --check src tests scripts evals .audit/journal-recovery/reproduce_baseline.py` | Exit 0, 169 files already formatted | `.audit/journal-recovery/format.log` |
| `python -m mypy` | Success on 67 source files | `.audit/journal-recovery/mypy.log` |
| `/private/tmp/unifi-hardening-tools.mNDAIe/actionlint` | Exit 0 | `.audit/journal-recovery/actionlint.log` |
| `git diff --check` | Exit 0 | `.audit/journal-recovery/diffcheck.log` |
| README local link and operator mirror checks | Every local README link target exists; operator guide body matches mirror | Direct Python assertions in implementation transcript |

The expanded recovery tests cover live unlink and same-path replacement during continuations and completion, loss between calls and restart, absence without creation in server readiness and issuer, stale generation refusal, fresh issuer-created version 2 use exactly once, malformed schema/generation/metadata and unexpected trigger refusal, strict version 1 refusal, deleted pending completion and continuation, restore-without-health-reset refusal, initializer existing-file/symlink/FIFO/directory exclusion, failed initializer preservation, and two concurrent exclusive initializers. Earlier exact-intent, secrets, principal/scope, one-use restart, grant selection, cancellation, queued intent, and context-cleanup tests remain passing.

One intermediate expanded run had 38 passing tests and one fixture failure because the manually modeled `block_client` intent omitted its normalized `dry_run=False` default. The test fixture was corrected, without changing production normalization. Initial `ruff format --check .` also included existing generated Markdown examples and found ten unrelated Markdown formatting differences; no generated prose was rewritten. Final checks use the project's Python scopes and the new reproduction script.

Deslop inspected the final diff for unnecessary comments, compatibility paths, broad exception-text trust, and unrelated prose churn. The parent will run the independent no-comments and source reviews after this freeze.

## Limits and remaining work

No selected security invariant is intentionally deferred. Independent source review, full suite, actual stdio and authenticated HTTP/verified HTTPS probes, installed desktop smoke, artifact rebuilding, advisory audit, and Trivy scans remain parent-owned gates. This report claims no new full-suite coverage result or built artifact verification.

The identity checks detect accidental storage loss/replacement. They do not provide protection against privileged rollback of both journal and grants or a narrow filesystem swap between checks. SQLite durability depends on supported local locking and sync behavior. The tests do not establish physical power-loss behavior, live firmware/account privileges, container storage, Kubernetes mounts, desktop application execution, or Windows/Linux bundle compatibility. Recovery requires stopped writers and operator inspection of uncertain controller outcomes.

Model the Domain kept journal state and generation ownership in `Authority`. Prove It Works changed verification to observable backend effects and real initializer calls. Deslop kept one initializer command and one shared completion transaction, without a recovery service or compatibility API.
