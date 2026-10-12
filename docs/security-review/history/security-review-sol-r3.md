# Independent adversarial review: f0693d4

Reviewed the full `b9870c7..f0693d4` fork diff and the surrounding grant, request, audit, confirmation, configuration, deployment, and release paths against the supplied intent. This is a read-only source and evidence review. I did not run tests, contact a controller, build or deploy an artifact, or infer a result from the parent's in-progress full suite.

## Findings

### 1. [critical] A queued write can proceed after audit cancellation marks authority unhealthy

**Location**: `src/mcp_unifi/authority.py:142-150, 180-238`; `src/mcp_unifi/modules/_audit.py:217-224`; `src/mcp_unifi/audit.py:276-285`

**Finding**: `Authority.begin()` checks `self.healthy` only before awaiting the audit sink. A concurrent completion can set it to `False` during that await, but the waiting invocation still consumes its grant and reaches the controller.

**Evidence**: Consider two calls using the same authority and separate grants. Call A has already made a controller mutation and is awaiting its completion `AuditLog.emit()`. Call B passes `begin()`'s health check at line 147, then waits for the audit log lock at line 180. Cancelling A while its completion sink is blocked releases that lock; the new outer `except BaseException` marks the authority unhealthy at `_audit.py:219-223`. `AuditLog.emit()` does not mark its own health unhealthy on cancellation because its handler catches only `Exception`. B's intent emit can then finish with `log.healthy == True`. `begin()` rechecks log health and grant expiry, but never authority health; it commits the pending attempt and `before_request()` proceeds to `client.request()`. The cancellation regression starts its second write only after A has finished and thus covers the immediate refusal, not this already-waiting call. This contradicts the fail-closed requirement that uncertain completion blocks later writes.

**Suggestion**: Recheck authority health after the awaited intent emit, immediately before the synchronous SQLite selection and commit. Add a deterministic test in which B waits on the audit lock before A is cancelled, then release B and assert that no second backend request occurs. Consider coordinating readiness and new admissions under one authority lifecycle if future awaits enter this interval.

## Attention: decision trail audit

- **Rows 30 and 37**: The frozen `9c4125e` raw log is now preserved and its tail supports `1371 passed` and `89.47%` coverage; `cleanup-checks.log` supports 23 affected passes at `0813ba8`. This closes the prior evidence-location concern. It does not verify the later `f0693d4` source: at this inspection, `full-suite-review-fixes.log` is still running, so row 41 correctly calls the new full run pending.
- **Rows 4, 7, and 38**: The append-only follow-up explicitly closes the open design comparison through `selected-design.md` and `design-judge.md`. I found no remaining ambiguity in that decision's status.
- **Rows 32, 33, 39, and 44**: The selected transcript records a Terra provider limit, later correction of a stale r3 retry paragraph, and a stopped early r3 dispatch. The trail correctly excludes an r1 verdict and treats the corrected prompt as the live round. The transcript does not support a separate raw terminal failure for each native r1 reviewer, and the trail no longer claims one.
- **Rows 41-43**: The actual MCP/HTTPS probe's fresh-identical-approval result and four durable outcomes appear in the selected transcript, while the new full suite remains pending. The workflow places the pinned rootfs scan before DXT archiving, but no remote release scan has run. The local Trivy vulnerability scan ended with `no space left on device` and produced no vulnerability verdict; the separate advisory and secret checks should not be described as a successful Trivy vulnerability scan. The row 43 limitation states this accurately.

The source checkpoint was clean at `f0693d4` when inspected. Docker runtime, Kubernetes mounts, physical power-loss behavior, desktop installation, release execution, and live controller behavior remain unverified by this review.
