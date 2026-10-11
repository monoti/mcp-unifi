# Selected hardening design

## Usage and outcome contract

Default startup is stdio, read-only, and verified TLS. Authenticated HTTP explicitly uses a loopback host binding. A trusted TLS proxy or tunnel is required for deliberate remote exposure. Read tools continue to use the current schemas. Source-controlled examples use the fork's local build rather than pulling an unmodified upstream image.

An operator may explicitly expose previews and write tools. An actual write additionally needs a short-lived exact-operation grant created outside MCP with a local operator command. The grant is read from an operator-owned directory mounted read-only into the server. The MCP tool catalog contains no grant-minting or grant-management operation. Protect the approval command and directory from the MCP caller's other tools. This boundary cannot constrain an agent that also has shell access as the approving operator.

The grant binds a trusted caller identity, resolved controller and configured site, original tool and all effective schema-validated arguments. Hash complete values including secrets before any redaction. Normalize omitted defaults before hashing. A grant cannot authorize a changed passphrase, another principal, another controller, or a second request after restart. A separate SQLite journal atomically persists one-use grant consumption and a sanitized prewrite intent, with durable transactions. Do not scan JSONL for replay state or invent a signing service.

Pending actions store their issuer and original effective intent. Compare ownership without consuming on a mismatch. Confirmation resolves the saved target and current authorization again, then passes through the same execution boundary as direct writes. A preview token remains ceremony, not consent.

## Types and ownership

- `Principal` is derived from authenticated HTTP context or operator stdio configuration, never from tool arguments.
- `MutationIntent` contains principal, resolved controller/site, tool and a SHA-256 digest of full effective arguments. A redacted projection is separate display/audit data.
- `OperatorGrant` contains a version, unique grant ID, matching intent digest, principal/target metadata and expiry. Parse and validate at the file boundary.
- `MutationAuthority` owns exact-grant matching and durable one-use consumption. The shared request context owns the effective outer tool intent. Composite steps and compensation use that approved outer operation.
- One execution guard protects every real controller write at the common backend/client seam. Middleware tags or caller `dry_run` booleans alone cannot establish no mutation. Explicit synthetic stub writes may retain test behavior only while no real backend can be reached.
- `PendingAction` owns immutable issuer and original intent. Registry consumption stays synchronous and single-use. Failed ownership checks leave another issuer's token intact.
- `redaction.py` owns opaque backup omission on both normal and refused audit paths. Error clients emit bounded status and stable diagnostic classes, never response text or transport exception strings. JSON and text logs omit unsafe traceback messages and causes.
- `audit.py` owns sink health, secure files and safe diagnostics. A durable prewrite record precedes network writes. Failed completion recording marks readiness unhealthy and blocks later writes. It cannot undo a completed controller write and must report uncertain outcomes honestly.
- `config.py` and `tls.py` own verified defaults and separate Access hub pinning. Source configuration and direct client constructor defaults agree.
- Deployment manifests own loopback publishing, writable restricted audit storage, readiness and fork build selection. Release workflows depend on exact-tag CI checks/scans. DXT dependencies install from the hashed lock and the project installs with no dependency resolution.

## Controller trust boundaries

Add a small operator configuration mapping authenticated client IDs to allowed resolved controller names. The configured site belongs to that controller. Enforce before backend resolution for reads and writes and again for saved confirmation targets. Resolve the `default` alias before authorization. Prevent aggregate registry calls from returning excluded controllers. Unknown configured principals and controllers fail closed. Avoid a generalized role system. Separate processes and controller credentials remain the independent isolation boundary.

## Synthesis decision

Use Sol's operator-file grant and backend execution boundary as the base. The cross-judge gpt-6-luna independently selected it. Graft Luna's audit readiness and failure lifecycle, and Terra's single execution capability and opaque-input policy. Correct the Luna and Terra proposal digests to include complete secret values before redaction. Use SQLite rather than Sol's hand-built file-lock replay journal. Reject the approval daemon and signature/key lifecycle for this local shared-mount deployment because they add services and protocol changes without required benefit. Never accept a caller `approved` boolean.

## Verification and scope

Regression tests cover each report finding, direct and confirmed writes, cross-principal tokens, exact-argument grants including changed secret values, one-use after restart, concurrent grant consumption, missing/unhealthy audit and no controller request on denial. Keep complete existing reads and explicit stub write behavior. Run actual stdio and authenticated HTTP MCP exchanges, with default refusal and scoped direct-call denial. Run full tests, lint, format, strict typing, manifest/version checks and current runtime audit.

No production secrets or controller operations are part of this run. Docker is installed but its daemon is not running. Render/validate deployment configuration and build artifacts where possible, and report runtime image/firmware verification separately. Live controller least privilege and firmware compatibility require the operator's environment.

## Implementation reconciliation

The implementation owner may adapt internal signatures while preserving these outcomes. Record deviations here or in its report and flag any missing invariant before claiming completion. Keep central guards small and preserve unrelated source.
# Storage recovery amendment from round 4

The [journal synthesis](journal-selected-design.md) extends this contract with strict v2 journal generation binding, external explicit initialization, non-creating MCP opens, runtime identity checks and exactly-one pending completion. It replaces silent request-time journal creation. Original caller, scope, immutable intent and external approval requirements remain authoritative.
