# Journal recovery candidate — generation-bound grants

## Problem

`Authority._connection()` currently creates the journal and schema on every open. A lost or replaced file therefore forgets consumed grant IDs; `complete()` accepts an update of zero rows, and the same grant file can authorize another controller request. The external exact-request approval, SQLite prewrite intent, and audit wrapper remain the contract. This design covers accidental storage loss or replacement, including across restart. It cannot establish history against an operator/root actor who deliberately restores both journal and grant state.

## Usage (caller's view)

Provision a private, durable journal once, before enabling real writes: `mcp-unifi-journal init` using `MCP_UNIFI_MUTATION_JOURNAL`. Start the server with the existing protected approval directory and journal path. `mcp-unifi-approve --principal alice --controller home --tool block_client --arguments-file args.json` requires that journal and writes a short-lived **v2** grant bound to its random generation. MCP still has no approval or journal-init tool.

The operator's normal call sites remain:

```python
# Outside MCP; validates effective tool arguments, reads the existing generation.
path = await create_grant(settings, identity="alice", controller="home",
                          tool_name="block_client", arguments=arguments, ttl=300)

# Real backend boundary; failure makes no controller request.
await authority.begin(controller="home", site="default")

# Audited tool wrapper, after the tool returns or fails.
authority.complete(operation, outcome="success")
```

If the journal disappears or changes, `/ready` returns 503 and real mutations refuse. The operator stops writable processes, inspects the controller and audit for pending/uncertain operations, and either restores the original journal or explicitly initializes a new one. A new generation invalidates every old grant, including unexpired files; the operator issues new approvals only after reconciliation. Expired files can be removed as routine housekeeping, but their presence does not block safe recovery.

## Shape

`authority.py` owns a single `Journal` component and the grant schema. No other runtime path creates tables or a file. `cli/journal.py` is the sole explicit initializer; `cli/approve.py` reads its generation through the same journal reader. `server.py` readiness asks the authority to check its journal. The existing `Operation`, audit middleware, backend hook, and exact digest remain the call path.

```python
@dataclass(frozen=True)
class JournalIdentity:
    device: int
    inode: int
    generation: str  # random UUID stored in singleton journal metadata

class OperatorGrant(BaseModel):
    version: Literal[2]
    id: str
    journal_generation: UUID
    digest: str
    principal: str
    controller: str
    site: str
    expires: float

def initialize_journal(path: Path) -> JournalIdentity:
    # TODO: operator-only command; O_EXCL 0600 creation, schema and generation
    # in one committed transaction, parent-directory fsync; refuse existing file.
    raise NotImplementedError

class Journal:
    def __init__(self, path: Path):
        # TODO: open existing only (SQLite mode=rw); validate owner, mode,
        # schema and generation; remember (device, inode, generation).
        raise NotImplementedError

    def generation(self) -> UUID:
        # TODO: used by the external issuer; fail if file identity changes.
        raise NotImplementedError

    def consume(self, grant: OperatorGrant, digest: str, redacted_intent: dict) -> None:
        # TODO: before any controller I/O: recheck identity, BEGIN IMMEDIATE,
        # match generation, expiration and unused ID; INSERT pending; commit;
        # recheck identity. Storage/identity failure marks unhealthy; an
        # ordinary stale, expired or consumed grant is a healthy refusal.
        raise NotImplementedError

    def complete(self, grant_id: str, outcome: str) -> None:
        # TODO: UPDATE ... WHERE grant_id=? AND outcome='pending'; require
        # rowcount == 1; commit and recheck identity; else mark unhealthy and
        # report uncertain outcome.
        raise NotImplementedError

    def check(self) -> bool:
        # TODO: readiness; same identity/schema check, no creation or repair.
        raise NotImplementedError
```

The `Journal` is one owner for file identity, generation, consumed IDs, and completion. Its public surface hides SQLite, file permissions, locking, and durability settings. `Authority` continues to own caller scope and matching a grant to the immutable `Operation`, then delegates the atomic consumption. A v1 grant is rejected, never inferred to belong to the current generation. Only the operator CLI can initialize. Existing in-flight `Operation.attempts` records its selected grant ID; an additional controller request in that same top-level operation uses the existing attempt, while a distinct invocation must consume a distinct grant.

Opening uses a non-creating SQLite URI (`mode=rw`), with owner-only and no-symlink validation. Check path `st_dev/st_ino` against the pinned identity before opening, after opening, and after every transaction; read and compare the metadata generation on the opened connection. SQLite still resolves a pathname internally, so checks cannot defeat a privileged actor swapping files between checks. They do catch ordinary unlink/replacement, including when a connection to the old inode remains open. Before a controller request, the post-commit check must have passed. `complete()` checks the same identity and exactly one pending row; zero rows cannot report success. Any mismatch makes the authority unhealthy until process restart after operator recovery. Do not auto-recreate on the server or issuer path.

Initial state is `uninitialized`; only explicit init transitions it to `ready(generation, identity)`. A successful consumption moves `unused grant -> pending attempt` in one transaction. Completion moves `pending -> success/error/uncertain` exactly once. A failed prewrite transaction makes no controller call and moves runtime to `unhealthy`; failure after a controller request reports uncertainty and moves to `unhealthy`. Replacement or disappearance at any runtime check moves to `unhealthy`. Restart with intact storage loads the same generation and consumed rows; restart without it refuses writes. Reinitialization creates a new generation, so old grants remain unusable. Two issuer processes may issue independent UUID grants against one generation; two server processes on a supported local SQLite filesystem serialize consumption through `BEGIN IMMEDIATE` and the primary key. Existing deployment guidance still limits replicas and excludes network filesystems.

Migration: stop writable server and issuers; back up the existing DB; migrate its intact `attempts` table in place by adding singleton metadata with a new generation and retain every consumed row. Reject old v1 files and issue only v2 grants after restart. If the journal is already missing, do not claim migrated history: explicitly initialize a fresh generation and reconcile any uncertain controller outcomes before new approval. Update the hardening/security guides and deployment bootstrap examples to show init, migration, and recovery. No secret values enter metadata or journal intent.

Regression targets: initialization refuses an existing path; a normal first write requires explicit init; live unlink and same-path replacement refuse before another controller request; completion with a missing or nonpending row reports uncertainty and fails readiness; restart with a missing file refuses; a new generation rejects old unexpired and expired v2 grants; intact migration preserves consumed IDs; concurrent server processes consume one grant once; two issuers create distinct usable grants. Assert zero controller calls for each denied write and keep existing exact-argument and secret-redaction tests.

## Synthesis decision

This runner chooses generation-bound v2 grants plus runtime file identity. A fresh journal cannot accept old grants, and a running server detects replacement even if a copy carries the same generation. Explicit init keeps state creation out of request handling. The orchestrator can compare this candidate with other runner designs.

## Tradeoffs accepted

- We accept a v2 grant format and an issuer/server upgrade together in exchange for restart-safe rejection of approvals tied to a lost journal.
- We accept explicit journal provisioning and recovery in exchange for eliminating silent request-time creation.
- We accept that a consumed grant file remains on disk in exchange for preserving the operator-controlled, read-only grant mount; the journal is the source of consumed state.
- We accept dependence on a local filesystem's SQLite locking and sync guarantees in exchange for a small single-file state owner. This is not proof of physical power-loss durability.

## Alternatives considered

- Runtime identity plus explicit initialization, refusing recovery while **any** old grant file remains: avoids grant-format migration, but exposes grant-directory cleanup policy to the operator and makes expired files block recovery. It still needs a correct runtime identity check. The journal interface is small; operational coupling is larger.
- Runtime identity alone with documented restart recovery: protects a live process, but a restarted process cannot tell an old unspent grant from one already consumed when the journal is gone. Documentation cannot enforce the one-use promise.
- Per-grant tombstones outside SQLite: introduces another writable authority and reconciliation rules; callers and maintainers must understand two consumption stores.

## Implementation reconciliation

Design only. No source changes or tests have been run for this candidate; accepted implementation deviations must update the usage, transitions, and owner contract here before handoff.

## Open questions and risks

- Does any supported deployment place the journal on storage whose rename, lock, or directory-sync behavior violates the local SQLite assumptions?
- Which existing installations contain intact v1 journals that need the in-place migration, and which need explicit loss recovery after inspection?

## Next implementation step

Add `Journal` opening/checking and an explicit initializer, then prove that live unlink/replacement and restart with a new generation produce zero additional controller requests.
