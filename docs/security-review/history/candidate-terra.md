# Candidate 3: signed-off write execution boundary

## Problem

At `b9870c7`, controller diagnostics can cross into MCP errors, logs, and audit; TLS and writes are opt-in; HTTP is publicly bindable; scopes identify modules but not a controller or site; pending confirmations are process-global; and a failed runtime audit write does not stop a write. The hard part is preserving useful read tools and the existing small server while making every controller mutation depend on identity, exact operator approval, and durable evidence. A preview/confirmation token is a replay interlock, not human consent, so it cannot be promoted into authorization.

## Usage (caller's view)

The ordinary MCP client remains read-only by default:

```text
stdio (default) -> list_wlans(controller="home")
HTTP loopback + bearer `ops-alice` -> list_wlans(controller="home")
```

For a write, the caller first requests a preview. The result is deliberately a non-secret summary plus `request_id`; it never contains an approval capability.

```text
preview_delete_vlan(controller="home", vlan_id="42")
=> { request_id: "req_…", action: "delete_vlan", target: { id: "42" },
     expires_at: "…", confirmation_token: "…" }

# Operator, outside MCP and outside the model's credential domain:
unifi-approve request_id=req_…
# shows canonical controller/site/action/arguments digest; operator approves exactly it

confirm_destructive_action(request_id="req_…", token="…")
=> deleted
```

`unifi-approve` talks to a local approval daemon over its own operator-authenticated interface. The daemon atomically releases a one-use permit to the server only after showing the exact canonical request. No approval token is returned to, accepted from, or logged by MCP.

## Shape

### Chosen shape: one write execution gate

Keep product tools and controller clients unaware of approvals. Add one `WriteExecutionGate` at the existing audited/middleware seam. Reads pass through normal caller scope and secrecy handling. A mutating tool reaches a controller only through `execute_write`; it resolves the caller and controller/site target again, consumes a caller-bound pending request, consumes the external exact-request approval, appends and fsyncs an audit *intent*, then invokes the controller. Thus a failed audit precondition makes **no** controller request.

The one public operation hides confirmation ownership, external approval IPC, re-authorization, durable ordering, and outcome recording behind a single capability. It is deeper than exposing policy, audit, and approval flags to each tool. This is boundary discipline: parse transport/configuration at the edge; internal code receives constructed domain values. It is not a general authorization platform: scopes remain static configuration and the approval daemon has exactly `show/approve` and `consume` semantics for this server's pending request digest.

```python
type PrincipalId = NewType("PrincipalId", str)
type ControllerName = NewType("ControllerName", str)
type SiteName = NewType("SiteName", str)
type RequestId = NewType("RequestId", str)
type ConfirmationToken = NewType("ConfirmationToken", str)
type RequestDigest = NewType("RequestDigest", str)  # SHA-256 canonical bytes

@dataclass(frozen=True)
class Caller:
    principal: PrincipalId
    allowed_modules: frozenset[ModuleName]
    allowed_controllers: frozenset[ControllerName]
    allowed_sites: frozenset[tuple[ControllerName, SiteName]]

@dataclass(frozen=True)
class WriteRequest:
    id: RequestId
    owner: PrincipalId
    tool: ToolName
    target: ControllerTarget  # validated controller + configured site
    canonical_args: CanonicalArgs  # schema-validated, secret-free projection
    digest: RequestDigest
    expires_at: datetime

class ApprovalBoundary(Protocol):
    async def consume(self, *, request: WriteRequest) -> None: ...

class DurableWriteAudit(Protocol):
    async def prepare(self, *, request: WriteRequest, caller: Caller) -> AuditLease: ...
    async def record_outcome(self, *, lease: AuditLease, outcome: WriteOutcome) -> None: ...

class WriteExecutionGate:
    async def preview(self, *, caller: Caller, command: WriteCommand) -> Preview: ...
    async def execute(
        self, *, caller: Caller, request_id: RequestId, token: ConfirmationToken
    ) -> ToolResult: ...
```

`preview` authorizes module/controller/site before storing `WriteRequest`; its pending store is keyed by opaque request id and records owner, digest, expiry, and an executor constructed from validated command data. `execute` performs, in this order: load without consuming; constant-shape owner/token check; re-authorize caller and target against current config; atomically consume the approval daemon's matching digest; call `audit.prepare`; then consume the pending request and invoke its executor. A denial, expiry, changed scope, changed configured site, unavailable approval daemon, or unavailable durable audit returns a generic refusal and makes no controller request. Request consumption occurs only after the durable intent, so a transient audit failure permits retry; approval consumption and request consumption must be coordinated by the daemon's idempotent request id so a crash cannot turn an approved request into a different write.

`Caller` is always constructed by transport code, never from tool arguments: HTTP maps a verified bearer to its fixed controller/site/module scope; stdio maps to one configured local principal with the same static scope. A deployment that cannot name that principal cannot enable writes. The controller registry accepts a `ControllerTarget` rather than an unchecked controller string, eliminating default-controller fallthrough for writes.

### Secrecy and audit ownership

`clients/errors.py` owns conversion of HTTP/retry/console failures into `ControllerFailure(code, request_id)` and never retains response bodies, headers, URLs with credentials, or exception text. The public error formatter maps known failure codes to bounded generic text. `redaction.py` owns structural redaction plus an `OpaqueInput` rule: serialized backup/restore payloads are omitted and represented only by byte count/digest; no arbitrary scalar is treated as safe. The same sanitiser is used before MCP envelopes, audit events, JSON logs, text logs, and exception/cause formatting. Audit records contain the request digest, public target summary, caller id, decision, and safe failure code—not raw args, raw result, `str(exc)`, token, or approval material. Reject `StdoutSink` at stdio startup.

`audit.py` owns readiness and durable file append. Write-capable startup opens the configured append-only audit volume and proves an intent write plus `fsync`; the health endpoint reports `ready` only while it remains healthy. `prepare` serializes a redacted intent and fsyncs it under its lock; a later sink failure marks it unhealthy. Read/refusal audit is best-effort and safe, but write execution requires a live `AuditLease`. A read-only-root container mounts a dedicated writable audit volume. Normal MCP error envelopes are classified as `refused`/`failed`, not success.

### Secure deployment and release ownership

`config.py` constructs safe-only configuration: stdio is default; `readonly=True`; HTTP, when intentionally enabled, binds loopback only and requires bearer authentication. Remote exposure is only through an authenticated TLS proxy/tunnel with no direct container port route. TLS is a sum type—`SystemCA` or `ExactPin(path)`—with no `false` variant. Each `ControllerConfig` has separate Network/Protect and Access trust values; `access_exact_pin` is required for an Access hub that is not system-CA verified and never reuses the gateway pin. Helm/Compose encode the same defaults, non-root/read-only root, explicit audit volume, and no all-interface plaintext port publishing.

Release owns its own sequence: checkout tag -> hash-locked install -> lint/types/tests/security scan -> build image and DXT from that tested source -> scan artifacts -> attest/sign/SBOM -> publish. DXT uses a checked-in hash lock and `pip --require-hashes`, then verifies its installed dependency set against the lock before zipping. Publication cannot start from merely green earlier CI.

### Module map

| Owner | Responsibility |
| --- | --- |
| `identity.py` / transport adapter | Construct `Caller` from HTTP bearer or configured stdio principal; no tool args. |
| `targets.py` | Resolve and authorize `ControllerTarget` from controller/site config. |
| `writes.py` | `WriteRequest`, pending store, `WriteExecutionGate`, and tool-facing preview/confirm adapters. |
| `approval.py` | Narrow UDS client for external exact-digest approval consumption. |
| `audit.py` | Sanitised append-only intent/outcome records, readiness, and `AuditLease`. |
| `errors.py`, `redaction.py`, `logging_setup.py` | Safe error codes and one sanitisation boundary for all emitters. |
| `config.py`, server/deploy manifests | Safe defaults, separate Access trust pin, transport and volume validation. |
| release workflow / DXT script | Release-local gates and reproducible hash-locked desktop bundle. |

## Alternatives considered

1. **Extend the existing preview token with caller id and a `writes_enabled` setting.** It hides little: every write still depends on the same caller/model obtaining both steps, so it lacks independent consent and encourages per-tool policy checks. It loses even though caller binding is retained in the chosen shape.
2. **A general RBAC/policy engine with dynamic grants.** It could express this, but exposes roles, grant evaluation, and lifecycle choices that the server does not need. Static caller scopes plus one external exact-request approval boundary hide more complexity behind the smaller interface.
3. **Have the MCP client submit an operator approval JWT.** This is simpler to deploy but places bearer approval material in tool arguments/transcripts and makes replay/secrecy harder. The daemon-consumed request digest keeps approval off MCP entirely.

## Tradeoffs accepted

- We accept a local approval daemon and operator step in exchange for preventing model-controlled confirmation from becoming authority.
- We accept unavailable-write behavior on audit or approval failure in exchange for a provable pre-execution evidence boundary.
- We accept no direct remote HTTP listener in exchange for avoiding plaintext bearer exposure; remote use needs an external authenticated TLS boundary.
- We accept migration of explicit stub writes in tests in exchange for production code having no broad test-mode write bypass.

## Trusted test path and rollout

Tests get a dependency-injected `TestWriteAuthority` only through a test server factory: it creates synthetic `Caller`, controller/site configuration, approval boundary, and durable in-memory audit, then explicitly approves the created request digest. Existing stub mutation expectations migrate through this helper; no environment flag, wildcard principal, or production default can grant writes. Add negative tests proving an unapproved/cross-principal/stale/controller-or-site-denied request makes zero backend calls, plus sink-failure-before-execution, Access-pin, stdio-stdout, error/log/audit opaque-secret, and real stdio/authenticated-loopback exchange tests.

Release in enforceable slices: (1) source error/secrecy and safe config/deployment defaults while retaining test helper; (2) caller-bound scope and target resolution; (3) pending request plus approval daemon and audit lease, then switch all mutations to the gate; (4) remove legacy direct confirmation/write paths; (5) release/DXT gates and published-artifact verification. Do not enable production writes until slice 3's synthetic integration tests and container audit-volume test pass.

## Open questions and risks

- Which local operator authentication mechanism is acceptable for `unifi-approve` on each supported host, and how is its audit retained independently of the MCP process?
- Is an external approval daemon acceptable for all supported desktop packaging targets, or should production writes be container-only initially?
- Which controller/site mapping is authoritative for products without an explicit site argument (especially Access), and should those writes remain disabled until modeled?
- Can the deployment guarantee one MCP process per trust domain? If not, controller credentials must be split before multi-tenant write enablement.

## Next implementation step

Write contract tests for safe error/audit projections and a minimal `WriteExecutionGate` test double before moving any real mutation through it.
