# Independent adversarial review: 0813ba8

## Findings

### 1. [critical] A consumed grant can shadow a fresh approval for the same operation
**Location**: `src/mcp_unifi/authority.py:159-217`; `src/mcp_unifi/cli/approve.py:54-70`
**Finding**: The server picks the first matching grant filename, regardless of whether that grant ID is already in the one-use journal. A fresh operator approval can therefore be refused while a consumed but unexpired file remains in the approval directory.
**Evidence**: The CLI creates a new UUID-named file for every approval and never removes older files. `begin()` gathers all matching, unexpired grants in sorted pathname order, sets `grant = matches[0]`, and inserts only that ID. If an earlier consumed UUID sorts before the new UUID, SQLite rejects it with `IntegrityError` and the code returns “already been consumed”; it never tries the fresh grant. UUID filename order makes this intermittent, and it is especially costly when the operator issues a replacement after an uncertain outcome as the operating guide instructs. The existing replay test uses only one file, so it cannot detect this path. The refusal makes zero controller requests, but authorized recovery or repeated identical writes can remain blocked until the old file expires or is manually removed.
**Suggestion**: Select an unconsumed matching grant within the same SQLite transaction used for durable consumption. Preserve a consumed grant's replay refusal when no fresh matching grant exists, and add a two-grant regression covering an old filename that sorts first.

### 2. [warning] The published DXT is not scanned as an artifact
**Location**: `.github/workflows/release.yml:106-150`; `.github/workflows/ci.yml:188-204`
**Finding**: The release job creates and attaches the DXT after reusable CI has scanned the source tree and Linux image. No step scans the assembled DXT before publication.
**Evidence**: The `verify` dependency runs Trivy against the repository and the CI image. The `publish` job then builds a host-platform DXT and passes it directly to `action-gh-release`. The archive's actual bundled files and dependencies are not an input to either scan. Hash-locked installs and the local Darwin import probe reduce risk, but they do not cover the Linux bundle produced by this release job. The channel has a scan gate, yet the published bundle is outside its scan coverage.
**Suggestion**: Scan the assembled DXT or its extracted bundle in the publish job and make release attachment depend on that result. Keep the artifact tied to the verified tag revision.

## Attention: decision trail audit

- **Row 30, frozen full-run evidence**: The `1371 passed` and `89.47%` figures agree with `/tmp/unifi-hardening-full-frozen.log`, which I read. The TSV points only to `implementation-report.md`; that report points to a temporary log outside the audit directory. The direct test output is available now but is not a durable review artifact. Preserve the raw log or a stable digest and command alongside the trail before relying on this row after the machine's temporary files are cleared.
- **Rows 24 and 28, durability scope**: The trail records the move to `synchronous=EXTRA`, `fullfsync`, and directory sync, and explicitly says no physical power-loss test ran. Treat the result as source and synthetic-path evidence, not a demonstrated power-cut guarantee on deployed storage. The implementation report correctly carries this limit.
- **Rows 32 and 33, prior review dispatch**: The selected transcript ends the earlier review turn with a provider usage-limit error; the later recovery checks and states that no report was produced. I found no basis for counting that dispatch as an independent verdict. This round reviews the unchanged `0813ba8` source.

The review is bounded to source, committed and local synthetic evidence, and the specified decision trail and transcript. I did not contact a controller, run Docker or Kubernetes, or execute publication.
