# Journal recovery candidate — Terra

## Process record

| Architect phase | Status | Record |
| --- | --- | --- |
| Ground | complete | `how-authority.md`, selected design, R4 review, authority/approval/tests/operator guide inspected. |
| Sketch | complete | Compared runtime identity plus explicit initialization, generation-bound grants, and runtime-only recovery. |
| Agree | autonomous | This candidate recommends generation-bound grants backed by an explicitly initialized journal. |
| Implement | not started | Design only. |
| Scrap | not indicated | The new boundary removes the repeated missing-state decision from the request path. |

## Problem

The one-use grant rule currently relies on an SQLite file that `Authority._connection()` recreates. Losing or replacing that file erases consumed IDs and permits a still-present exact grant to be used again; `complete()` can also silently update zero rows. The repair must retain the existing external exact-intent approval, make accidental journal loss safe across restart, and detect runtime replacement without claiming to withstand an operator/root adversary who can restore arbitrary privileged filesystem history.

## Usage (caller's view)

Writable installation has an explicit one-time state step; server startup and approval issuance only open existing state.

```sh
# once for a new empty protected state directory
mcp-unifi-journal init --path /protected/state/mutations.sqlite

# operator approves a normalized, exact callable request against that journal
mcp-unifi-approve --principal alice --controller home --tool block_client \
  --arguments-file /protected/operator/block-client.json --ttl 300

# server starts normally; no write-capable endpoint creates or repairs journal state
mcp-unifi
```

After accidental journal loss or replacement, `/ready` is 503 and every real write is refused. The operator first stops writers and investigates the controller and protected storage. For absence, the operator initializes; for an unexpected replacement, the recovery command first archives that database to an owner-only operator-supplied path, syncs both parent directories, then initializes a new generation:

```sh
mcp-unifi-journal recover --path /protected/state/mutations.sqlite \
  --archive-to /protected/recovery/mutations.sqlite.untrusted
# prior grants now fail generation matching; issue a new exact approval only after review
mcp-unifi-approve ...
```

The existing caller-facing write path remains small:

```python
# client hook; no recovery or generation argument leaks into a tool
await target.authority.begin(controller="home", site="default")
response = await controller_request()
target.authority.complete(operation, outcome="success")
```

The approval CLI is the second consumer:

```python
journal = MutationJournal.open_existing(settings.mutation_journal)
grant = OperatorGrant.issue(intent=normalized_intent, journal_id=journal.identity)
write_grant_once(settings.approval_dir, grant)
```

## Shape

`MutationJournal` becomes the sole owner of journal opening, initialization, identity validation, grant consumption, and completion. `Authority` stays the small policy seam: it validates principal/scope, reads an exact grant, writes the sanitized audit intent, then asks its already-open journal to consume it. The approval CLI opens the same journal only to read its identity before minting a grant. Neither path has a create-if-missing branch.

```python
JournalId = NewType("JournalId", str)       # UUID-format opaque generation
GrantId = NewType("GrantId", str)
FileIdentity = tuple[int, int]               # (st_dev, st_ino), process-local binding

@dataclass(frozen=True)
class OpenJournal:
    path: Path
    identity: JournalId
    file_identity: FileIdentity

class OperatorGrant(BaseModel):
    version: Literal[2]
    id: GrantId
    journal_id: JournalId
    digest: RequestDigest
    principal: PrincipalId
    controller: ControllerName
    site: SiteName
    expires: float

class MutationJournal:
    @classmethod
    def open_existing(cls, path: Path) -> MutationJournal: ...  # not implemented

    @classmethod
    def initialize_empty(cls, path: Path) -> JournalId: ...     # not implemented

    @property
    def identity(self) -> JournalId: ...                         # not implemented

    def consume(self, grant: OperatorGrant, intent: SafeIntent) -> None: ...
    def complete(self, grant_id: GrantId, outcome: Outcome) -> None: ...
    def record_uncertain(self, grant_id: GrantId) -> None: ...
```

`initialize_empty` is an operator CLI operation, not a server method. Under an exclusive initialization lock it accepts only an absent, secure path; creates the SQLite database and schema with `meta(key PRIMARY KEY, value NOT NULL)` containing a random `journal_id`; commits with the existing durable settings; syncs the file and parent directory; then releases the lock. It refuses a non-empty path. `recover` is separately explicit: with writers stopped, it atomically archives a verified regular-but-untrusted existing database to an empty owner-only destination, syncs both directories, then calls `initialize_empty`; it never overwrites either path. A separate explicit `migrate-v1` command may add `meta.journal_id` to an existing valid v1 journal while preserving `attempts`; it does not replace the file or erase history. All three commands reject symlinks, unsafe ownership/modes, and unexpected SQLite sidecar files.

`open_existing` validates the parent and regular database before opening it, opens SQLite without schema creation, validates the expected schema and exactly one UUID `journal_id`, captures `(st_dev, st_ino)`, and checks the same identity before every transaction and after each transaction. Missing path, wrong kind/mode/owner, changed inode/device, malformed metadata, SQLite errors, or a zero-row completion permanently mark that process's authority unhealthy. A restarted server performs this open check before serving writable readiness; it does not infer that an absent database is new.

`consume` uses one SQLite `BEGIN IMMEDIATE` transaction. It first revalidates the live file binding and `grant.journal_id == meta.journal_id`, then inserts the pending row by `grant_id` (primary key) with the already-redacted intent. A conflict refuses before any controller request. `complete` updates the single pending row for that grant and requires `cursor.rowcount == 1`; otherwise it fails closed as an uncertain controller outcome. The wrapper retains the present finally-path: completion failure marks authority unhealthy and best-effort records `uncertain`, never enables a later write.

The journal identity is deliberately inside the grant, whereas the request digest still binds principal, resolved controller/site, tool, and full normalized arguments (including secret values before redaction). Thus a newly initialized journal cannot accept an old grant even when its ID, digest, and expiry match. The public `Authority.begin/complete` API does not grow: recovery complexity is hidden in one module (interface depth; boundary-discipline, make-operations-idempotent).

### State transitions

| State | Event | Result |
| --- | --- | --- |
| `absent` | server/approval opens | refuse; writable readiness false; no file creation |
| `absent` | explicit `init` on verified empty path | `ready(journal_id=N)` |
| `ready(N)` | approval | v2 grant bound to `N` |
| `ready(N)` | matching `consume` transaction | `pending(grant_id)` before network |
| `pending` | exactly-one-row completion | terminal outcome, grant remains consumed |
| `ready/pending` | missing/replaced/invalid file at runtime | process `unhealthy`; no new controller request |
| `absent` after stop | explicit `init` | `ready(N+1)`; all grants for `N` refuse |
| `replaced` after stop | explicit archive-and-`recover` | `ready(N+1)`; archived state is not trusted and all grants for `N` refuse |

Concurrency is owned by SQLite's transaction lock: multiple server processes may use one local journal only if they share the same protected local filesystem and schema; concurrent consumption of a grant produces one insert and one refusal. The initializer/migrator serializes itself with a sibling owner-only lock file and refuses while a live writable server is using the state; deployment remains single writable replica as documented. Multiple approval issuers may read the identity concurrently, but `O_EXCL` grant creation and journal primary keys preserve distinct IDs and one consumption. SQLite's opening race is handled by the initializer lock plus post-open metadata/file-identity checks; a normal server never executes DDL.

This detects ordinary deletion, replacement, accidental empty reinitialization, and stale grant replay. It intentionally does not guarantee recovery from power loss beyond SQLite/filesystem sync semantics, recover outcomes after a controller request, or distinguish a hostile privileged rollback that restores both a prior journal and matching old grant files; protecting against that requires an independent append-only/remote trust boundary outside this local design.

## Synthesis decision

Choose **B, generation-bound grants**, grafting **A's** explicit initialization and runtime inode binding. B is the only small shape that safely gates a restart after lost history: an operator may create new state, but that state rejects all approvals minted against its predecessor. A alone detects loss while a process lives but cannot know, after restart, whether an old grant belongs to a destroyed predecessor. C is rejected because documentation cannot turn unknown consumed history into authorization.

## Tradeoffs accepted

- We accept an explicit `init`/`migrate-v1` operator step in exchange for never treating a missing database as fresh writable state.
- We accept invalidating unexpired approvals after journal recovery in exchange for preventing replay of approvals whose consumption history was lost.
- We accept one local SQLite writer topology and a protected shared filesystem in exchange for a single durable source of consumed-grant truth.
- We accept detection rather than resistance to privileged history rollback in exchange for avoiding a new signing/remote quorum service outside the stated threat boundary.
- We accept fail-closed uncertainty after a zero-row completion in exchange for never reporting a durable outcome that was not recorded.

## Alternatives considered

- **A: runtime identity plus explicit initialization only.** It hides runtime checks well but exposes an unsafe restart decision: a fresh initialized journal has no way to reject valid-looking old grants. It loses to B.
- **C: runtime-only check with documented restart recovery.** It has the smallest implementation but exposes security-critical history interpretation to operators and permits old-grant replay after documented recovery. It is insufficient.
- **Remote signed epoch service.** It would survive local privileged rollback better, but exposes key/service lifecycle and availability requirements to operators; that is materially broader than this local hardened fork.

## Migration and regression targets

1. Existing v1 writable deployments start not-ready until the operator runs explicit `migrate-v1` (preserving rows) or `init` for a known-new path. Issuance and execution reject v1 grants; the one-hour maximum limits stale operational debris but is not relied on for security.
2. Prove a consumed v2 grant cannot replay after a normal restart; deletion/replacement during a live process flips readiness to 503 and sends no later request; after explicit re-init the same grant fails journal-ID matching; a newly issued matching grant succeeds once.
3. Prove completion with zero affected rows marks authority unhealthy, emits/attempts `uncertain`, and blocks subsequent writes. Cover malformed/missing metadata, path mode/owner/symlink rejection, expired files, and init refusal when a database exists.
4. Race two server authorities and two issuers: exactly one same-grant consumer reaches the fake controller; distinct grants work; initializer/migrator cannot race a writer; approval issuance never creates journal state.
5. Add an integration probe for readiness across server restart and a docs migration example that requires controller-state inspection before a replacement approval. Tests are evidence for these paths, not a power-loss, network-filesystem, or hostile-root guarantee.

## Implementation reconciliation

No implementation has started. Keep `Authority` as policy/wiring and put all SQLite/path/generation logic in `mutation_journal.py`; do not add a production test bypass or let MCP tools initialize, migrate, or inspect recovery state. If repository constraints require a different lock primitive or SQLite journal mode, record the accepted deviation here and retain the state transitions above.

## Open questions and risks

- Can the supported container/Helm storage guarantee same-host local SQLite locking and directory sync for the one writable replica, or should writable mode reject storage types it cannot identify safely?
- Should `migrate-v1` be permitted only before server start, or may it coordinate a deliberate maintenance window using an operator-supplied stop assertion?
- Is the operational cost of invalidating every outstanding grant after recovery acceptable, given the current maximum one-hour TTL and mandatory controller-state review?

## Next implementation step

Extract `MutationJournal.open_existing()` with a failing test that a missing path never appears during server or approval execution, then implement explicit initialization and v2 journal-bound grants.
