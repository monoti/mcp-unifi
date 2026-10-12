# Security review, Sol, round 4

Checkpoint: `cae347af47e96f7fbdad3989065f28404680d827`. Reviewed the upstream diff, authority and client request paths, confirmation and scope paths, audit lifecycle, deployment and release surfaces, earlier R2/R3 reports and triage, and the decision trail. Source was not changed. No controller or credential was used.

## Findings

### 1. [critical] A missing journal can be silently recreated and a consumed grant reused

**Location**: `src/mcp_unifi/authority.py:110-130, 195-240, 242-260`

**Finding**: `_connection()` creates a new SQLite file whenever the journal path is missing, on every call. It does not distinguish first initialization from disappearance of an already used journal. `complete()` does not check whether its `UPDATE attempts` matched a row. If the journal file is removed or replaced while the server stays up, completion can report success without its durable outcome, and a later identical call can consume the same still-present grant again.

**Evidence**: Call A commits grant G and its pending intent in `begin()`, then reaches the controller. If the journal path is lost before `complete()`, `_connection()` creates a fresh file and table. `UPDATE attempts SET outcome=? WHERE grant_id=?` affects zero rows, raises no exception, and leaves `Authority.healthy` true. The wrapper sets `completion_recorded=True` and returns success. A later call with the same effective arguments still finds grant G in the approval directory; the empty new table reports G unused, so `begin()` inserts it and can make a second controller request. This requires journal loss or replacement outside the MCP caller's normal permissions; it is a storage failure case, not an MCP-input bypass. The current owner-only storage policy reduces likelihood, but the claimed fail-closed durable one-use boundary does not survive this failure.

**Suggestion**: Bind an authority instance to an initialized journal identity and fail closed if that file disappears or changes during its lifetime. Require exactly one row to be updated on completion. Document and gate recovery from a missing journal after restart, since a fresh file cannot establish prior grant consumption.

### 2. [warning] Fork README sends operators to upstream security guidance and claims unpublished channels

**Location**: `README.md:13, 39, 50, 71, 87, 121-129`

**Finding**: The fork README calls Pete's upstream tool manifest and security/configuration pages the current reference for this fork, while also saying the fork has no published artifacts. Its distribution paragraph still says Smithery and MCP Registry are registered/listed.

**Evidence**: This checkout has its own hardened security guide and `astro.config.mjs` targets `monoti.github.io/mcp-unifi`, but the README's security and configuration links point to `pete-builds.github.io/mcp-unifi`. An operator following those links can receive upstream defaults and deployment directions that do not describe exact grants, controller scopes, and durable journal requirements. The publication claim at line 87 directly conflicts with line 17. These are public operating instructions for the security boundary, not just stale branding.

**Suggestion**: Link the fork's local or fork-hosted guides and tool manifest, and label upstream pages as historical references where needed. Remove unpublished distribution claims until each channel exists and has passed its release gate.

## Attention: decision trail audit

No separate trail-integrity flag. Rows 36-47 map the four accepted R2 findings, the two accepted R3 findings, their fix checkpoints, and the current pending full-suite gate without treating cancelled dispatches as verdicts. The transcript and preserved logs support the distinction between earlier completed suites and the final run. At review time, `full-suite-final.log` had collected 1,379 cases but had no terminal result; the current protocol and backend JSON artifacts report three stdio reads, HTTP auth/scope denial, zero unauthorized mutations, and four granted mutations. They do not prove live controller compatibility. Row 43 correctly says the local Trivy vulnerability database download failed and produced no verdict. No remote publication, Docker/Kubernetes runtime, desktop installation, physical power loss, or actual controller operation was established.
