# Cross-judge: UniFi write authorization designs

Scores are 1 (poor) to 5 (strong), against the brief and the six requested criteria. “Coverage/enforceable control” includes every real backend mutation path, including nested/composite/confirmation execution; a generic `mutates` tag or `dry_run` check by itself does not count as enforcement.

| Criterion | Sol | Luna | Terra |
| --- | ---: | ---: | ---: |
| Coverage / enforceable control | 5 | 3 | 4 |
| Independent exact consent | 4 | 4 | 4 |
| Secrecy | 4 | 3 | 3 |
| Controller scope and confirmation | 5 | 4 | 4 |
| Read compatibility | 5 | 5 | 4 |
| Maintainability | 4 | 3 | 2 |
| **Total / 30** | **27** | **22** | **21** |

## Verdict

Use **Sol as the base**, with a narrower contract around its mutation boundary and the durable journal. This best fits the stated preference for operator-file grants, keeps the new public surface small, and explicitly recognizes that tool middleware cannot prove a `dry_run` branch made no write. Retain its rule that the guard sits immediately before every real backend mutation and that composites, backup restore, queued closures, and controller-side actions cross the same boundary.

Adopt these grafts:

- From **Luna**: startup must refuse writable service when the audit sink is unusable; audit intent is durably written before a controller request; completion failure makes the writer unhealthy; retain stable error codes and reject stdout audit for stdio. These are useful operational invariants without adopting signed permits.
- From **Terra**: model the write boundary as one narrow capability/gate and make opaque inputs (especially serialized backup payloads) non-reconstructable in diagnostics. Keep its transport-built immutable caller/target values and re-check current controller/site scope on confirmation.
- From all candidates: preview tokens prove possession of pending state only. They never count as consent. Preserve existing read tools and their transport shapes, subject to configured read scopes.

Do **not** graft Luna's approval object into MCP arguments or Terra's local approval daemon/UDS protocol. Both expose more consent machinery and operational surface than this fork needs. A token or signature on the MCP call also increases transcript/log exposure. The operator grant must be created outside MCP and mounted read-only to the server.

## Important corrections to the base

1. **Bind the actual effective request before redaction.** Build a versioned canonical representation after argument validation/defaulting and target resolution. Include every value that can affect the backend request, including secret values; omit only controls proven not to affect execution (for example a presentation-only dry-run flag). Then compute the authorization digest. Redaction is a separate projection for grant display, audit, logs, and errors. Never compute the authorization digest from scrubbed arguments: two different secrets could otherwise match one grant. Prefer a keyed digest/HMAC when low-entropy secrets could be guessed from a plain hash; make key ownership and CLI/server sharing explicit. Do not persist the raw canonical request in grant or audit files.
2. **Use an actual guarded backend seam.** A generic FastMCP middleware checking `mutates=True`, `dry_run`, or caller kwargs is insufficient: it cannot establish which nested branch ran, and internal helpers/confirm closures may bypass it. Route all real backend mutation methods through one private capability/adapter that validates the current `ApprovedAttempt` and target immediately before dispatch. Add an inventory check so new backend mutators cannot be registered outside that path. Never hand unguarded real backend objects to tool modules.
3. **Make approval consumption and audit durable without a hand-built replay scan.** Keep operator grants immutable/read-only. Use SQLite with its built-in transactional journal for the server-owned one-use consumption and audit intent/outcome records. In one transaction, verify the grant is unconsumed, insert a unique consumed-grant/intent record, and commit durably before network I/O. Unique constraints provide replay rejection after restart; no cross-process JSONL scan or ad hoc file-lock protocol is needed. Record outcome separately; if outcome persistence fails, mark write readiness unhealthy and block subsequent writes. A crash after intent remains an explicitly indeterminate operation, and the consumed grant stays consumed. Validate SQLite durability assumptions for the mounted volume and document that unsupported network filesystems are not a multi-replica coordination mechanism.
4. **Keep scope ownership explicit.** Principal identity comes only from authenticated HTTP identity or trusted stdio launcher configuration. Resolve aliases/default controller and configured site before checking both read/write scope and hashing intent. Missing identity, controller, site, or grant denies. Confirmation must bind to the original principal and target, re-check current scope, and only execute the stored validated intent. Caller-supplied controller/site text or `principal` fields cannot override resolved values.
5. **Separate exact consent from class policy.** Operator scope files limit principal to controller/site/module/effect classes; an exact-request one-use grant separately represents approval of the specific operation. Require both. A writable-mode environment switch may expose previews or the write-capable tool surface, but never authorizes execution on its own.

## Candidate-specific findings

**Sol** is strongest on the central backend seam, resolved targets, confirmation ownership, and matching exact grants. Its phrase “hashes secret values without logging them” needs the correction above: ensure the digest is over the effective secret value before redaction, and avoid a plain hash where guessing is feasible. The proposed JSONL lock-and-replay-scan journal is unnecessary complexity; replace that portion with a transactional SQLite owner. Its caller example says a grant for one direct setter and its confirmation example describes a separate destructive grant; specify clearly that the destructive grant binds the original action and stored arguments, not `confirm_destructive_action(token=...)` as a fresh intent.

**Luna** has strong safe defaults and audit lifecycle details, but `args_digest: canonical JSON after validation and secret scrubbing` is unsafe if “scrubbing” removes or normalizes secret values before digesting. Its middleware ordering cannot guarantee that all real backend writes are guarded, especially nested calls; the later closure guard helps confirmations but leaves direct internal/composite paths dependent on conventions. Approval passed through tool JSON is also unnecessary exposure. Its restart-invalidates-preview choice is compatible with the brief, provided grant consumption/audit stay durable.

**Terra** clearly articulates a single execution gate, trusted identity, and external consent separated from the MCP client. It is the best alternative if a shared operator/server filesystem is unacceptable. However, its `canonical_args: ... secret-free projection` creates the same exactness bug unless a separate digest binds the original effective secret values. More seriously, its proposed order consumes external approval, then writes the audit intent, then consumes pending state; an audit failure can strand approval, and cross-service idempotency becomes part of correctness. SQLite can atomically couple grant consumption and audit intent in this local-server deployment. The daemon, approval IPC, and extra service lifecycle broaden scope and public surface contrary to the parent constraint. It also describes the preview response as containing a confirmation token despite saying approval capability is never returned; clarify the token as a non-authorizing lookup handle.

## Compatibility and implementation boundary

Existing read tools should continue to resolve through the existing controller registry and preserve their schemas and useful results. Apply read scopes before execution; safe error conversion must not flatten successful reads into generic failures. Keep preview behavior available where it is currently safe, but make its no-write property observable in tests. Do not widen this design into cloud Site Manager authorization, multi-tenant policy engines, or daemon deployment support.

No controller or implementation verification was performed for this judgment. The source check confirms the concrete `confirm_destructive_action` closure and existing `dry_run` tool pattern in `network/mcp-unifi`; those patterns reinforce the need for a backend seam rather than middleware-only enforcement.
