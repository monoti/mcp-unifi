# Journal recovery cross-judge

## Scores

Each axis uses the brief's 0-3 scale. These are design scores, not implementation evidence.

| Candidate | Runtime replay | Restart loss | One owner, small interface | Operator migration | Regression targets | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Sol | 3 | 3 | 3 | 2 | 3 | 14 |
| Luna | 3 | 3 | 2 | 2 | 3 | 13 |
| Terra | 3 | 3 | 1 | 2 | 3 | 12 |

All three retain the external exact-request grant and bind v2 grants to a journal generation. All require an existing journal for server and issuer, pin the runtime file identity, consume before controller I/O, and reject a zero-row completion. Each gives useful tests for deletion, replacement, restart, reinitialization, and concurrency. Sol has the smallest owner boundary because `authority.py` already owns the SQLite behavior. Luna and Terra add a separate journal class and module boundary without a clear caller need. Terra adds `recover` and `migrate-v1` commands, a lock-file protocol, and extra identity types. Those make more recovery states and races to explain and test.

## Recommendation

Use Sol as the base. Keep generation-bound v2 grants, runtime device/inode checks, non-creating SQLite opens, and an explicit operator-only `mcp-unifi-journal init`. Keep the SQLite owner in `authority.py`; a small initialization entrypoint may call an initialization function there. Preserve `Authority.begin` and `Authority.complete` as the server interface. The approval CLI reads the generation from the existing journal and never creates state. Server readiness reports unhealthy when the journal is absent, replaced, malformed, or inaccessible. The process remains unhealthy after a runtime storage failure until operator recovery and restart.

Graft Luna's clear lifecycle rule: normal startup and approval issuance open existing state only, and the initializer refuses an existing path. Graft Terra's explicit state-transition table and its regression case that a newly issued grant succeeds once after recovery. Retain Sol's distinction between an invalid grant, which is a healthy refusal, and failed journal storage, which makes the authority unhealthy. Retain the existing principal, resolved controller/site, tool, and effective-argument digest checks. Neither a generation match nor an MCP preview constitutes operator approval.

For this unpublished fork, remove the proposed `migrate-v1` and automated `recover` commands. During upgrade, stop writable processes and issuers, preserve the v1 journal and grant files as a private archive for inspection, then explicitly initialize a new empty journal generation at the configured path. The v2 issuer and server reject every v1 grant. Old v2 grants also fail after any later new generation. Operators inspect pending or uncertain operations and controller state before issuing a replacement approval. A retained expired grant file does not prevent initialization because generation matching, rather than directory emptiness, blocks its use. If preserving a deployed v1 journal ever becomes a requirement, design an in-place migration then, with its own recovery and verification rules.

Reject the alternative init gate with retained v1 grants. Its safety depends on an atomic empty-directory check across approval issuers and recovery, and expired files block progress. Reject runtime-only identity plus documented restart recovery because it cannot distinguish a consumed grant after state loss. Reject Terra's automated archive/recover, migrate command, extra lock and abstract identifier types for this release. Reject adding a new `MutationJournal` module or class merely to move current SQLite code out of `Authority`; extract it only if the implementation reveals a concrete ownership conflict.

## Required invariants and proof targets

- `init` alone creates the journal, schema, and random generation at a previously absent protected path. It refuses an existing file, symlink, or unsafe owner/mode and reports success only after committed, synced state and parent directory entry. Server and approval CLI use non-creating opens and validate the expected schema and generation.
- An authority pins device, inode, and generation at open. It verifies the path before and after SQLite open and on both sides of consume and completion transactions. A changed or missing path fails readiness and prevents another controller request, including when an old connection remains open. The checks detect accidental replacement, not a privileged adversary who controls filesystem history or a narrow swap between checks.
- Consume checks principal, target, exact effective arguments, expiry, grant version, and generation. `BEGIN IMMEDIATE` and the grant ID key allow one pending insert and prewrite intent commit before controller I/O. A denied grant makes zero controller calls. Concurrent issuer processes can create distinct grants; concurrent server processes cannot consume the same grant twice on supported local SQLite storage.
- Completion changes exactly one pending row. Zero rows, a storage failure, or replacement after a controller request makes the outcome uncertain and the authority unhealthy; it cannot be reported as a durable success. Recovery does not clear uncertainty automatically.
- Tests cover live unlink and same-path replacement, restart with missing state, reinitialization rejecting an unexpired old v2 grant, rejection of v1 grants, successful fresh v2 use once, zero-row completion, issuer/server races, and existing exact-scope and redaction behavior. Verify with an isolated journal and fake controller. These tests do not prove power-loss behavior or hostile root rollback.

This remains a design judgment. No source was changed or behavior tested in this cross-judge pass.
