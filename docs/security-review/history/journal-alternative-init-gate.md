# Competing shape A, explicit initialization with retained v1 grants

Operator runs `mcp-unifi-journal init` once. Runtime only opens the existing file with mode=rw. Approval continues to issue v1 grants. On loss, stop writers and inspect controller outcomes. Initializer refuses if any *.json remains in the protected grant directory, even expired files. Operator archives every grant before initializing fresh empty state. Thus initialization cannot silently replay a retained grant. No runtime path creates tables or a file.

```python
def initialize_journal(path: Path, grants: Path) -> None:
    # operator-only, exclusive creation; refuse any retained grant
    raise NotImplementedError

class Authority:
    file_identity: tuple[int, int] | None
    def _connection(self) -> sqlite3.Connection:
        # open existing only; check pinned inode before and after open and commit
        raise NotImplementedError
    def complete(self, operation: Operation, outcome: str) -> None:
        # require one pending row, otherwise unhealthy and uncertain
        raise NotImplementedError
```

This preserves the existing grant format and gates missing-journal restart at initialization. It creates operational coupling between a writable grant directory and journal provisioning. Every expired grant must be archived before recovery. Approval must use the same external initialization lock to prevent concurrent issuance during the empty-directory check. Server mounts can stay read-only, but the operator coordinates two stores. A privileged actor restoring grants after initialization is outside the trusted boundary, as is restoring old consumption history. Compared with generation binding, the init gate exposes more recovery coordination through a smaller code change.
