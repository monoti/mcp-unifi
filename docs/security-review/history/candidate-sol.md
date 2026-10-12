# Candidate design: operator grants at the mutation boundary

## Problem

The current fork treats `MCP_UNIFI_READONLY=false` as authority to mutate. Direct setters execute immediately, while destructive previews store a process-global closure that any holder of the token can confirm. `@audited(mutates=...)` classifies tools, but the write gate is installed only in read-only mode; audit sink failures are swallowed. Controller error bodies, exception chains, logs, and opaque audit arguments can carry secrets. The design must close those paths while preserving the existing Network, Protect, and Access tool shapes, the resolved controller/site behavior, and useful read and preview calls. The local controller API remains the target; no cloud Site Manager assumption is needed.

## Usage (caller's view)

Default quickstart: stdio or authenticated local HTTP, verified controller TLS, read-only controller key, and read-only MCP tool list. The operator can explicitly set `MCP_UNIFI_READONLY=false` to expose mutating tools and allow dry-run and destructive preview calls. Applying any real mutation additionally requires an operator-created, exact-request grant in a read-only mounted grant directory. The MCP process has no tool, endpoint, or writable path that can create a grant. A real deployment must configure an audit volume and explicit principal-to-controller/site permissions before enabling writes. Synthetic stub tests can set a separate `unsafe_stub_writes` test-only option; startup rejects that option when any real backend exists.

```python
# Operator creates this outside MCP with a local CLI that never talks to the model.
# No credential or request body is printed; only the canonical intent digest.
grant = approve_intent(
    principal="desktop-operator", controller="home", site="default",
    tool="set_port_state", args={"port_idx": 3, "enabled": False},
    expires_in_seconds=300,
)
# CLI writes one read-only grant file with grant id, principal, target, tool,
# SHA-256 of canonical effective arguments, expiry and schema version.

# Direct setter: the model can make this call, but the operator grant decides
# whether it reaches the real backend. Omitted controller resolves to home
# before digest and permission checks; a grant for another controller fails.
await mcp.call_tool("set_port_state", {"port_idx": 3, "enabled": False})

# Destructive flow: preview is allowed in explicitly enabled write mode;
# neither its token nor a caller claim approves the eventual deletion.
preview = await mcp.call_tool("delete_vlan", {"network_id": "vlan-42"})
# Operator reviews the preview's exact effective intent and creates the grant.
await mcp.call_tool("confirm_destructive_action", {"token": preview["token"]})
```

HTTP principal comes from the validated bearer token's stable `client_id`; stdio principal comes from operator process configuration. No JSON argument, model text, or confirmation token can choose it. Unauthenticated HTTP may remain an explicit read-only localhost mode; real writes require authentication. The operator CLI may use the same canonicalization package but cannot be exposed as an MCP tool or called by the server on the model's behalf.

## Shape

```python
@dataclass(frozen=True)
class Principal:
    id: str                 # trusted transport/config input only

@dataclass(frozen=True)
class Target:
    controller: str         # resolved canonical registry name
    site: str               # from ControllerConfig, not caller-supplied default
    module: str

@dataclass(frozen=True)
class Intent:
    principal: Principal
    target: Target
    tool: str               # original effecting tool, not confirm tool
    canonical_args_sha256: str
    effect: Literal["apply", "confirm"]

@dataclass(frozen=True)
class PendingAction:
    token: str
    owner: Principal
    intent: Intent
    snapshot: Mapping[str, Any]
    expires_at: datetime
    executor: Callable[[], Awaitable[str]]  # private, checked by apply boundary

class MutationAuthority:
    def check_target(self, principal: Principal, target: Target) -> None: ...
    def prepare(self, intent: Intent) -> ApprovedAttempt: ...
    # Privately: verify exact operator grant, atomically consume id and fsync
    # intent record before returning. No public boolean `approved` parameter.

async def apply_real_mutation(
    *, intent: Intent, operation: Callable[[], Awaitable[T]],
    authority: MutationAuthority, audit: DurableAudit,
) -> T: ...

def put_pending(intent: Intent, snapshot: Mapping[str, Any], executor: Callable[[], Awaitable[str]]) -> Preview: ...
async def confirm(token: str, principal: Principal) -> str: ...
```

`Intent` is derived after Pydantic/FastMCP argument parsing, defaults, registry alias resolution, and controller/site resolution. Canonical serialization is versioned, deterministic, includes every argument affecting the write, excludes only presentation controls such as `dry_run`, and hashes secret values without logging them. A grant matches principal, controller, site, module, original tool, digest, expiry, and one-use id. On confirmation, compare the pending owner before consuming the token, then recheck current target permission, grant, and audit readiness; execute only the stored intent. Wrong-principal attempts leave the token intact. Avoid accepting a `principal` or `approved` parameter from tool JSON. Use a private `ContextVar` for trusted request identity and effective intent, with strict setup/reset around each call; missing identity denies real writes. The original `@audited(mutates=...)` classification remains the single tool inventory and registration completeness check, but classification alone no longer authorizes a write.

The deepest enforceable seam is immediately before each real backend mutation, including direct setters, composite steps, backup restore, queued closure execution, and controller-side actions such as speed tests. Pass a private `ApprovedAttempt` capability to real backend write methods (or keep all real backend write access behind one checked adapter); callers cannot manufacture it from tool arguments. This is the part a new tool cannot bypass by copying a nearby direct setter. Static tests enumerate backend mutators and reject unguarded calls. Stub backends have no reference to real clients. `dry_run` and preview must perform no mutation, and their classification may remain mutating for visibility under read-only mode. If a `mutates=True` tool has an actual apply branch, that branch must cross the capability seam; the middleware cannot infer from `dry_run` alone that no writes occur.

`MutationAuthority` owns target permissions and grants, not each tool. An operator file maps principals to explicit `(controller, site, module, read/write)` scopes; absent entries deny. Apply the read scope before tool execution and again on confirmation's stored target, so omitting `controller`, selecting a default alias, or confirming an old token cannot switch sites. Keep controller credentials least privilege in deployment examples; the server can reject missing scopes, but cannot prove a UniFi key's upstream role without controller access. Do not expose a real backend object to modules that can bypass this authority boundary.

For one-use grants and durable audit, use a single local append-only journal on a writable mounted volume. Under an OS file lock across processes, scan/check consumed grant ids, append a redacted `write_intent` record with grant id and intent digest, flush and `fsync`, then release the lock and call the controller. A repeated grant id is refused, including after restart. After the response or exception, append a `write_outcome` record; an outcome append failure marks the authority unhealthy and blocks subsequent writes. A crash after intent and before outcome leaves an explicit `unknown outcome` for operator reconciliation, never a free replay. This intentionally consumes a grant even when the controller rejects a request. `DurableAudit.preflight()` runs at startup/write readiness; an unwritable mount or unsupported sink prevents write mode. Reads can continue with a reported audit fault if their audit sink fails, but writes cannot proceed without a durable prewrite record. `/health` remains liveness; readiness reports audit failure. JSONL can remain the replay surface if journal records are compatible, and stdout/syslog alone cannot satisfy durable write mode. Stdio rejects any stdout audit sink.

At the data boundary, clients return stable error codes, status and route labels, never raw `resp.text`, controller `message`/`detail` strings, or `str(httpx.HTTPError)`. Keep raw exceptions only in memory without `raise ... from exc` where a formatter might expose chained text. Network `_request`/`_v2_request`, Protect JSON/binary, Access, console probes, and retry all use one safe diagnostic constructor. Tool `err(...)`, telemetry and both text/JSON log formatters receive only safe diagnostics. The audit decorator records scrubbed structured fields; `error` is scrubbed too. Opaque inputs such as `backup_json` are represented as length/digest or `[REDACTED]` on both normal and refusal paths, never copied into audit records. Redact before any formatter or sink, including traceback text; source elimination remains the primary defense. A domain error envelope records `success=False` and `denied_by` where relevant, instead of a false success.

Config ownership remains `config.py`/`tls.py`: default controller and Access TLS verification true regardless of inline/file secrets, and a distinct `access_pinned_cert` plus `access_tls_verify` for the Access hub. Pin failures are startup errors; a gateway pin never silently covers Access. Explicit insecure TLS can remain an operator escape hatch with a clear startup warning and no silent fallback. Default `readonly=True`, `mcp_host=127.0.0.1`; Compose binds host loopback and Helm keeps ClusterIP with no public ingress, audited volume and readiness wiring. HTTP on a non-loopback address requires an explicit protected transport boundary (TLS at proxy/ingress or equivalent) and authentication; do not ship a public plaintext example. Default example controller credentials should be read-only.

Release ownership stays in workflows: tag publication first runs the same locked dependency install, lint, types, full tests, security/dependency scan and artifact checks as CI on the tag commit; image push, DXT attachment, chart/registry publication depend on a single passing release gate. DXT installs wheel dependencies from `requirements.lock` with `--require-hashes`, then installs the project wheel `--no-deps` into the bundle; verify wheel version and dependency closure before zipping. Avoid floating `pip install --target ... .` and floating install-time tools. For third-party publisher downloads, pin version and checksum. The module surface stays small: config/TLS, one authority module, one audit owner, and one safe-diagnostics module; transport and tool bodies carry no grant parsing policy.

## Synthesis decision

Candidate for arena synthesis. The preferred base is the exact-intent, operator-file grant with one durable journal owner; no other runner has been evaluated in this file.

## Tradeoffs accepted

- We accept a deliberate operator approval step per real write in exchange for model-independent consent covering direct and confirmed writes.
- We accept consuming a grant before contacting the controller in exchange for no replay after crash or timeout; an unknown outcome requires readback and a new grant.
- We accept an audit volume and local file locking for write mode in exchange for one auditable, restart-safe one-use boundary.
- We accept a migration of old tests that assumed writable defaults in exchange for true default denial. Stub fixtures may opt into `unsafe_stub_writes` only with synthetic backends.

## Alternatives considered

1. **Policy-only allowlist:** Operator config could permit selected tools/controllers for a client, and confirmation could require only the token. This has a smaller implementation but leaves the model able to invoke any permitted write without independent human review. It exposes risky policy interpretation to every tool caller and fails the consent requirement.
2. **Signed exact-request grants:** An offline operator CLI signs each `Intent`; the server holds only a public verification key. This cleanly separates minting, but introduces key management, signature format/version migration and replay persistence anyway. A read-only mounted operator file has the same authority separation here with a smaller public surface. Prefer signed grants if the server and operator cannot share a trusted mount.
3. **Middleware-only approval:** One FastMCP middleware could check mutating tags and kwargs. It cannot reliably distinguish previews from apply branches or protect a pending closure and nested composite/backend write. Its shallow interface hides too little of the write policy.

## Implementation reconciliation

No implementation yet. The implementer should update this contract if a real backend mutation cannot be placed behind the single checked seam, rather than adding a second authorization route.

## Open questions and risks

- Does the deployment require multiple server replicas sharing an audit volume? If yes, verify the chosen filesystem's `flock` and fsync guarantees or use a transactional external journal; a per-pod `emptyDir` is insufficient for replay safety.
- Which controller API roles permit each read feature while denying writes? This requires a synthetic permission matrix or operator validation against actual firmware; no real controller test is authorized here.
- Should explicit insecure TLS be allowed in real mode at all, or restricted to loopback/test deployments? Either choice must be conscious and tested.

## Next implementation step

Build the safe diagnostic and audit prewrite primitives, then place every real backend mutation behind `apply_real_mutation` before enabling grant parsing or migrating tests.
