# Journal recovery candidate

## Problem

The v1 authority consumes an exact external operator grant in SQLite before a controller request, but `_connection()` silently creates a database and schema whenever they are absent. If storage disappears, the same grant appears unused; `complete()` also treats a zero-row update as success. Recovery must preserve external approval and exact-request scope, stop writes when durable history is lost, and let an operator recover without claiming protection against privileged rollback of both journal and grants. This design follows the current `Authority.begin`/`complete` flow and SQLite durability note. The requested security-hardening guide path was absent from this checkout; the selected design and existing authority/tests were used as grounding.

## Usage (caller's view)

At initial setup, the operator explicitly initializes the mutation journal in the protected state directory before issuing any grants:

```sh
mcp-unifi-journal init
mcp-unifi-approve --principal alice --controller home --tool update_wlan --arguments-file args.json
```

Restarting the server preserves the journal generation and existing consumed-grant set. The MCP server opens the existing journal in read/write mode but never initializes it. Approval records that generation in the grant.

If journal storage is missing or replaced, startup refuses writable readiness. After confirming the intended protected directory and dealing with retained grant files, the operator explicitly initializes a new generation; old grants cannot match it. Expired grants can be removed by the operator as normal file cleanup. No MCP tool initializes or repairs this state.

```python
await authority.begin(controller, site)  # returns only after grant consumption + intent commit
authority.complete(operation, "success")  # raises and poisons authority unless exactly one row changed
```

## Shape

Use one private SQLite journal as the authority for a random `generation_id`, grant consumption, and prewrite intent. `meta(singleton=1, generation_id)` is created only by the explicit operator initializer. Each grant carries `generation_id` as a strict required field. The approve CLI reads the initialized generation and embeds it in the new grant; it does not initialize the journal. The server's runtime handle captures both that generation and the file identity `(device, inode)` at startup.

The server opens an existing file only (`mode=rw`), checks owner-only permissions, validates schema and generation, and checks the path identity before and after opening. Before each transaction and before accepting its result, it verifies that the path still names the captured device/inode and that the database metadata still contains the captured generation. Any mismatch, open failure, SQLite error, or failed invariant marks the authority unhealthy and refuses further writes. Holding an SQLite connection is not treated as proof that the pathname still points to that database. SQLite's own transaction lock remains the serialization mechanism across server processes; grants are single-use through the primary key and `BEGIN IMMEDIATE`.

```python
@dataclass(frozen=True)
class JournalIdentity:
    generation: UUID
    device: int
    inode: int

@dataclass(frozen=True)
class OperatorGrant:
    version: Literal[2]
    id: GrantId
    generation: UUID
    digest: Digest
    principal: PrincipalId
    controller: ControllerName
    site: SiteName
    expires: UnixSeconds

class MutationJournal:
    @classmethod
    def initialize(cls, path: Path) -> JournalIdentity: ...  # operator CLI only; exclusive create
    @classmethod
    def open_existing(cls, path: Path) -> "MutationJournal": ...  # never creates
    def identity(self) -> JournalIdentity: ...
    def consume_and_record(self, grant: OperatorGrant, intent: SanitizedIntent) -> None: ...
    def complete(self, grant_id: GrantId, outcome: Outcome) -> None: ...  # require rowcount == 1

class Authority:
    journal: MutationJournal  # no nullable/uninitialized runtime mode
    healthy: bool
    async def begin(self, controller: ControllerName, site: SiteName) -> None: ...
    def complete(self, operation: Operation, outcome: Outcome) -> None: ...
```

`begin` retains the existing sequence: validate trusted principal/scope and exact normalized intent; find a valid grant with the current generation; emit the existing audit intent; revalidate journal identity and grant expiry; atomically insert the consumed grant and sanitized intent. Within the same `BEGIN IMMEDIATE` transaction, an already consumed ID refuses. The process-local operation map continues to avoid duplicate consumption for composite steps of one approved outer operation. `complete` updates the consumed row and requires `rowcount == 1`; zero or multiple rows poison readiness and raises an uncertain-outcome error. Completion cannot undo a controller write. If storage changes during an in-flight request, the authority becomes unhealthy and reports uncertainty.

The operator initializer is the sole schema creator and generation owner. It creates the parent/state file with owner-only permissions, commits a random generation, and syncs the file and containing directory before reporting success. It refuses to overwrite an existing database. Reinitialization is an explicit operator action after a lost/replaced journal: retained grants with the prior generation are unusable, even if their expiry has not passed. A privileged operator who restores both an old journal and matching grants can roll back history; this local design does not claim to prevent that. It also does not claim power-loss guarantees beyond SQLite `synchronous=EXTRA`, filesystem sync support, and the storage device honoring barriers.

The public runtime surface stays small: `begin` and `complete` keep owning mutation policy, while `MutationJournal` hides schema, open mode, generation validation, locking, and row-count checks. The initializer is a separate operator entrypoint because its authority and lifecycle differ from the server. No audit JSONL parsing or signing service is added. Validation of grant JSON and filesystem state stays at CLI/server boundaries; inner journal methods receive parsed domain types. This follows boundary discipline and gives each journal state one writer policy.

## Synthesis decision

This candidate chooses generation-bound grants plus explicit journal initialization (shape B), with runtime file-identity checks from shape A. A alone needs a safe restart recovery gate and can accidentally authorize retained old grants if a replacement journal is reinitialized with no persistent identity binding. Generation binding makes this invariant local: every grant names the journal generation that was current when the external operator approved it.

## Tradeoffs accepted

- We accept a new explicit initialization step in exchange for making database creation visible and preventing MCP startup from silently resetting replay history.
- We accept a version-2 grant migration in exchange for rejecting legacy grants whose journal generation cannot be established safely.
- We accept that reinitialization invalidates all outstanding grants in exchange for simple, fail-closed recovery semantics.
- We accept startup refusal when storage identity is ambiguous in exchange for keeping mutation readiness tied to a single protected journal.
- We accept no protection against an operator with sufficient privilege restoring both old journal and matching grant files; that is outside this local boundary.
- We accept SQLite `EXTRA` and explicit directory sync as the durability contract, without claiming arbitrary power-loss or device-cache behavior.

## Alternatives considered

- **Runtime inode/identity pin only (A):** exposes fewer grant changes but leaves recovery dependent on a carefully managed “old grant files must be gone” rule. Generation-bound grants move that recovery invariant into the approval data and make the hidden journal state easier to validate.
- **Runtime-only pin and documented restart recovery (C):** smallest implementation, but insufficient because a restart after journal loss forgets consumed IDs and can accept a still-valid grant. Documentation cannot make the old generation distinguishable.

## Implementation reconciliation

No implementation changes are part of this candidate. Preserve the old external approval flow and digest; add only the generation binding and journal lifecycle contract. If the existing settings or CLI structure cannot provide an operator-only initializer, record an explicit revised entrypoint and maintain the invariant that normal server startup never creates state. Update this section with accepted deviations and their source before handing off implementation units.

## Open questions and risks

- Should an initialization command live beside `mcp-unifi-approve`, or should approval itself initialize only on an explicit `init` subcommand?
- Can the deployment mount preserve SQLite rollback journal locking and directory sync semantics across all supported storage backends?
- Is the project willing to invalidate outstanding grants on every journal recovery, including accidental file loss?
- Does a same-device/inode database modified in place by privileged external tooling need additional immutability policy, or is that within the operator-trust boundary?

## Next implementation step

Implement and exercise the explicit initializer plus read-only-to-initialize runtime open contract first, then bind grants to its generated identity before changing completion semantics.
