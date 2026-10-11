# Comment review, round 2

Reviewed `0813ba8..f0693d4` in `network/mcp-unifi`. Acceptance scope is added or edited comments and suppressions, as clarified by the parent. Source remained frozen. This report is the only file written.

## Proposed deletions

Two comment fragments, two lines. No source deletions were applied.

| File at f0693d4 | Line | Proposed deletion | Reason |
| --- | --- | --- | --- |
| `src/mcp_unifi/authority.py` | 270 | `# The committed pending intent still prevents replay if storage has failed.` | Explains our own recovery design. The journal primary key, committed insertion in `Authority.begin`, and selection that excludes every existing grant ID express replay prevention. This is not an external platform surprise. |
| `.github/workflows/release.yml` | 122 | Inline `# v0.36.0` only | Human-readable action version annotation. No public API contract, legal header, external behavior constraint, or issue/RFC link. Preserve the pinned action hash and executable YAML. |

## Root-cause flag

`MUST KILL src/mcp_unifi/authority.py::Authority.completion_failed`: its name conceals the intentional best-effort journal update and swallowed persistence errors; rename or extract that recovery operation so best-effort uncertain-outcome persistence is visible without the deleted explanation. Preserve synchronous unhealthy state and replay prevention. This is a clarity flag, not evidence that catching these failures is incorrect.

## Keeps and suppressions

No added or edited comment qualifies for a keep. No added or edited docstring appears in the diff. No added or edited lint, type, or security suppression appears in the changed executable files. The removed `_audit.audited` commentary remains deleted.

The changed `Settings.readonly` Field description is executable schema metadata describing operator configuration. Keep it; deleting it would change the published configuration description. Markdown operating instructions and findings are documents, not code comments or docstrings. Keep the changed operator instructions and evidence descriptions.

## Scope and verification

Read the no-comments skill, Codex mapping, comment-sicko reference, prior acceptance artifact, diff, surrounding authority and audit code, release workflow, and changed documentation. Searched changed executable files for suppression markers. Confirmed the new comment's claim against the committed journal insertion and consumed-ID query in `Authority.begin`. No runtime tests were run by this reviewer; the source is frozen and the parent owns behavior verification.

Unchanged comments and docstrings in `config.py`, `_audit.py`, and `release.yml` are outside this fresh acceptance scope. Prior accepted keeps and suppressions were not reopened. Generated `.audit/review-fixes` logs were not treated as source comments. No credentials, commits, pushes, deployments, or child agents were used.

Touched file: `.audit/unifi-hardening/no-comments-r2.md` only. Applied deletion count: zero. Proposed deletion count: two fragments on two lines. One named clarity flag. No restored comments or reruns.
