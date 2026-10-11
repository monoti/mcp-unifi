# Luna adversarial security review, r4

Reviewed `network/mcp-unifi` at `cae347af47e96f7fbdad3989065f28404680d827` against upstream `b9870c768362d5e5b1321c7048a9fc7c035a9c59`, including the full diff, surrounding authority/audit/deployment paths, supplied reports, prior R2/R3 reviews and responses, and the specified decision trail and transcript. This was a read-only review. I did not run tests, access credentials, contact a controller, build or deploy artifacts, or publish anything.

## Findings

### 1. [warning] Desktop setup recipes still install Pete's unmodified upstream server
**Location**: `docs/site/src/content/docs/recipes/claude-desktop.md:27,50,88`; `docs/site/src/content/docs/recipes/cursor.md:50`
**Finding**: The fork's published setup recipes direct users to run `git+https://github.com/pete-builds/mcp-unifi` and Claude Desktop's one-click path to Pete's releases. Those commands do not install this hardened fork. A user following the real-mode stdio recipe can therefore run upstream code with the supplied controller API key and bypass the fork's read-only default, external exact-operation grants, caller scopes, and repaired TLS defaults. Cursor's page has a fork-hardening notice but its stdio command contradicts it; Claude Desktop's page has no equivalent notice.
**Evidence**: Claude Desktop's stub and real examples both set uvx `--from` to Pete's repository (lines 27 and 50), and its DXT alternative links to Pete's release page (line 88). Cursor's stdio example repeats the upstream repository at line 50. The fork's DXT and image publication is explicitly pending, so these cannot be replaced by assuming a hardened fork release exists. The multi-site page itself now tells readers to use the hardened fork guide, demonstrating the needed boundary, but that warning is missing from the actual Claude Desktop page and is contradicted by the Cursor invocation.
**Suggestion**: Make these fork docs point to an installable local fork checkout/source revision and fork-owned artifacts only after they exist. Until then, clearly mark upstream recipe commands as upstream-only and remove or disable the real-mode path that reads like a supported hardened-fork setup.

## Attention: decision-trail audit

- **Row 47 and transcript ordinals 2404–2407**: Row 47 correctly records the 139 focused checks as complete while the 1,379-case full suite and final independent review are pending. The selected transcript later shows the final real-backend and diagnostics JSON being read; those files record successful synthetic HTTPS/MCP checks and false leak flags. That evidence does not resolve the full-suite status, which must remain pending until its actual log reaches completion. Append a follow-up trail row for the final protocol results and the eventual suite result rather than letting row 47's earlier checkpoint stand as the last verification state.
- I found no basis in this run's transcript to count the earlier stopped dispatch as a verdict or to claim publication/deployment. The prior trail corrections continue to distinguish those events.

## Review limits

No live controller, Docker/Kubernetes runtime, desktop installation, remote release, or physical power-loss behavior was verified. I did not infer success from in-progress suite sessions or from owner summaries.
