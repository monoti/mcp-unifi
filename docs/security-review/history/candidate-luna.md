# UniFi MCP hardening candidate: signed, exact-request permits

## Problem

The fork already has module scopes, explicit mutation tags, read-only middleware, TLS pinning for the console, confirmation closures, scrubbing, audit sinks and release workflows. The holes cross those boundaries: ownership is based on bearer `client_id` while stdio has none; a confirmation token is only a lookup key; direct writes do not use confirmation; `readonly` currently defaults off; Access has no independent certificate pin; audit sink failure can be swallowed; and diagnostics may contain response bodies, tracebacks or opaque argument strings. Configuration toggles alone cannot represent one human's approval of one exact mutation. The design therefore adds one small external signing step, keeps controller authorization and transport policy in their current owners, and makes a durable audit append a prerequisite to every real write.

## Usage (caller's view)

Read-only is the default. An operator who enables mutation starts the server with secure controller configuration, scoped controller grants and a public key for the approval signer. A direct change requires an approval generated out of band for the exact controller, tool and arguments:

```console
mcp-unifi-approve --proposal proposal.json
# Operator reviews the displayed controller, tool, and redacted change, then confirms locally.
# Emits approval.json signed by the operator's local key.
```

```python
# Direct change: the approval travels with the call, but it is not created by MCP.
await client.call_tool("set_port_state", {
    "controller": "home", "port_id": "p-12", "enabled": False,
    "approval": load_operator_approval("approval.json"),
})
```

Destructive changes still use preview and confirmation. The preview is bound to the authenticated principal. A separate local approval command signs its canonical digest; confirmation requires both the same principal and that independent approval:

```python
proposal = await client.call_tool("delete_vlan", {"controller": "home", "vlan_id": "guest"})
approval = operator_approves_outside_mcp(proposal)  # explicit local human step
await client.call_tool("confirm_destructive_action", {
    "token": proposal.token, "approval": approval,
})
```

The token proves only that the server retained a proposal. The HTTP principal proves only who is calling. Neither is consent. For stdio, server startup requires an OS-authenticated operator identity configured by the launcher; approval is still signed out of process. There is no anonymous stdio write mode.

## Shape

### Ownership and boundaries

- `config.py` owns validated defaults and transport/controller trust settings. It defaults `readonly=True`, controller TLS verification on, HTTP bind to loopback, and disallows plaintext HTTP on a non-loopback bind. Add `access_pinned_cert` with its own validation and TLS context; never reuse the console pin.
- `authorization.py` owns principal resolution, controller/site grants, exact approval verification and mutation policy. HTTP principal comes from the verified token's immutable client identity. Stdio principal comes from a configured launcher identity, never tool arguments or a proposal token. Unresolved identity denies.
- `modules/network/_pending.py` owns preview payload, digest, TTL and state transition. Pending state belongs to a principal and controller. It can be consumed once only after all checks and durable `started` audit append succeed.
- `audit.py` owns scrubbed audit records and durability. Startup opens/checks the configured sink before registering a writable server. For every write, failure to append+fsync a `started` event refuses execution. Completion append failure causes a failed health/readiness state and blocks subsequent writes; it cannot undo a network change already sent. Audit error fields are stable codes, not exception text.
- Existing backend clients retain controller requests and response parsing. Their raised exceptions become safe typed errors without response excerpts; callers and logs see a request id and error class/code only.
- CI/release owns publication ordering and dependency artifact integrity.

### Caller-facing signatures

```python
@dataclass(frozen=True)
class Principal:
    id: str                  # authenticated token client_id or launcher identity
    source: Literal["http-token", "stdio-launcher"]

@dataclass(frozen=True)
class MutationTarget:
    controller: str
    site: str
    tool: str
    args_digest: str         # canonical JSON after validation and secret scrubbing

@dataclass(frozen=True)
class HumanApproval:
    target_digest: str
    principal_id: str
    issued_at: datetime
    expires_at: datetime
    nonce: str
    signature: bytes

class ApprovalVerifier:
    def verify(self, approval: HumanApproval, target: MutationTarget,
               principal: Principal, now: datetime) -> None: ...

class Authorization:
    def principal_for_request(self, context: RequestContext) -> Principal: ...
    def check_controller(self, principal: Principal, controller: str,
                         site: str, tool: str) -> None: ...
    def authorize_mutation(self, principal: Principal, target: MutationTarget,
                           approval: HumanApproval | None) -> None: ...

class AuditLog:
    async def prepare(self) -> None: ...  # writable+durable sink probe or fail startup
    async def begin_mutation(self, event: AuditEvent) -> AuditReceipt: ...  # append+fsync, fail closed
    async def finish_mutation(self, receipt: AuditReceipt,
                              outcome: SafeOutcome) -> None: ...
```

The operator's approval CLI and MCP share only the canonical `MutationTarget` encoding and signature format. The private key stays outside the server; MCP has only trusted public keys. Approval binds the principal, controller, site, tool, exact validated arguments, expiry and nonce. A signature cannot be replayed for changed arguments, another controller, or another principal. Clock skew/expiry, invalid signatures, missing key, or nonce replay deny.

### One mutation path

`@audited(mutates=True)` remains the single source for mutation classification and tags. A mutation middleware in `scoping.py` (or its replacement) sits at the last common call boundary and calls `Authorization` for every mutating tool, including `confirm_destructive_action`. Then the audit decorator validates and scrubs arguments, writes+fsyncs `started`, and only then invokes the tool body. This catches ordinary direct writes and destructive confirmation closures. The closure itself calls the same authorization service immediately before its backend call, using the saved proposal target and current principal; it never treats a token as approval. The duplicate check closes gaps when a closure is invoked internally or by a future call path.

For destructive preview tools, `_pending.py` creates a random opaque handle, stores the canonical target, validated closure, owner principal, controller/site and expiry. The returned preview exposes only the handle and human-readable redacted summary. Confirmation atomically claims then consumes it after signature, ownership, scope, target and audit checks. On any rejection, nothing is sent to the controller; state stays consumed only for a verified execution attempt, otherwise it expires normally. Process-local pending state is acceptable because restart safely invalidates proposals.

Controller permissions are explicit operator policy keyed by principal and controller/site, with read and write tool classes. Tool arguments cannot select a controller outside the grant. Grants load once from a root-owned config file; unknown principal/controller/site is deny. This is separate from module scope, which can continue hiding tools but is not controller authorization.

### Safe failures and logs

Clients raise `ControllerError(code, request_id)` without body snippets or exception chaining that could retain raw transport data. Diagnostics log fixed event names, sanitized endpoint labels and request ids; formatter output and traceback paths scrub both message and exception causes. Tool errors are a fixed public message plus request id. Audit stores scrubbed validated arguments, target digest, principal id, policy decision, stable error code and outcome; it never stores raw exception text or unstructured result text. The refusal path validates and scrubs attempted inputs before audit. Stdio startup rejects any audit sink that writes to protocol stdout.

### Deployment and release boundaries

Secure defaults: read-only on; TLS verification on for Network, Protect, Access and console; Access pin is separately configurable; HTTP binds loopback by default and cannot expose plaintext on wildcard/public binds; HTTP auth is mandatory off loopback. `readonly=False` plus explicit principal/controller write grants and approval public key are all required before mutations are reachable. A read-only root container gets an explicit writable audit volume; failure to mount/initialize it leaves the service unready and unable to write.

Release tag workflow must depend on passing lint, types, tests, secret/dependency scans, and tool-manifest checks before artifact build/publication. DXT dependency resolution uses the checked-in hash lock (or generates and verifies an equivalent hash lock); build fails if any dependency lacks a pinned hash. Publish DXT SHA-256 alongside the artifact and verify it in release CI. CI tests stdio and authenticated HTTP MCP exchanges with synthetic secrets and a test-only stub-write mode that cannot be selected with real backends.

The public API stays small: configuration, a verifier, one authorization service and one audit facade. It hides signature canonicalization, principal extraction, scope intersection, sink readiness and mutation sequencing. Transport and controller wire structures stay private, per information-leakage and minimize-reader-load principles.

## Synthesis decision

Standalone candidate; synthesis is pending. This design chooses signed exact-request human approval outside MCP over an operator-file policy. A policy file can constrain what writes are possible, but it cannot show that a human approved each actual request. A signed permit does both without turning the MCP server into an approval UI or creating a general policy platform.

## Tradeoffs accepted

- We accept operating a small local approval command and protecting a signing key in exchange for verifiable human consent per exact write.
- We accept extra approval input on every direct write in exchange for having no implicit allow path when a broad write flag is enabled.
- We accept invalidating pending confirmations at process restart in exchange for keeping proposal storage in-process and fail closed.
- We accept denying writes when audit storage is unavailable, and potentially reporting an uncertain completion if the final audit append fails, in exchange for never knowingly executing an unaudited mutation.
- We accept default read-only and TLS verification migration work in exchange for safe first-run behavior.

## Alternatives considered

- Operator policy file with approved tools/controllers: compact and easy to audit, but callers must learn policy syntax and it authorizes classes of future writes rather than a human approving each actual payload. It hides less consent complexity while leaving the key question unanswered.
- Signed approval tokens embedded only in destructive confirmation: smaller migration to existing call sites, but direct mutating tools bypass it. It exposes inconsistent rules to callers and leaves a second write path.
- External approval daemon: centralizes identity and signing and could support multiple servers, but introduces a network service, availability dependency, protocol and key lifecycle disproportionate to this fork. It hides more internals but is a new authorization platform.

## Implementation reconciliation

No implementation has started. Keep every mutation routed through the shared guard and audit path; if a backend path cannot be reached through it, redesign that path before implementation proceeds. Migrate all direct mutating tool calls and confirmation closures together, then remove legacy unguarded helpers in the same change.

## Open questions and risks

- Should the operator approval CLI sign with a local key file protected by OS permissions, or use an OS key store when available?
- Does the current HTTP authentication provider expose immutable token client identity in every supported HTTP transport mode, and what launcher supplies stdio identity in the intended deployment?
- Which controller role or API permission model can be enforced by UniFi itself versus only documented as an operator responsibility?
- Which deployment manifests and DXT tooling can consume a hash lock directly, and where should release checks be shared to avoid duplicating CI gates?

## Tests and migrations

- Error boundary tests inject unique synthetic secrets into Network, Protect, Access, retry, console and HTTP failures; assert absence from returned tool errors, text/JSON logs, chained tracebacks and audit JSONL.
- Test structured and scalar error bodies, arbitrary exception text, refused scope/controller/approval calls, backup restore arguments and formatter traceback handling. Verify stdio rejects stdout audit.
- Authorization matrix covers direct writes, internal closure execution and confirmation: missing/forged/expired/replayed approval, wrong principal, changed args, wrong controller/site, unknown identity and read-only mode all refuse before backend invocation. Positive tests assert exactly one invocation.
- Audit tests fail startup on unusable sink; fail-closed before backend on start append failure; stop future writes on completion append failure; concurrent calls yield complete ordered JSONL records. Test read-only-root deployment volume wiring.
- Config tests cover TLS/read-only/bind defaults, loopback HTTP, public plaintext rejection, independent Access pin mismatch and required HTTP auth. MCP protocol smoke tests run real stdio and authenticated HTTP over stubs.
- Release workflow tests prove publication waits for all gates, DXT lock rejects unhashed dependencies, and artifact hash is emitted/verified. Stub-only write injection has an explicit test-only config type that cannot be constructed when any real backend is active.
- Migration: default existing installs to read-only and TLS verification; update compose/Helm examples with audit volume and explicit read-only setting; document per-controller/site grants, local signing setup, approval CLI and stdio principal identity. No production controller writes or secret reads are part of migration verification.

## Next implementation step

Add the canonical target, principal, and signed-approval types plus verifier/authorization unit tests, then route a single direct mutator and its confirmation path through the shared fail-closed boundary before migrating the remaining mutation inventory.
