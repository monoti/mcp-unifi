from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import stat
import time
import uuid
from contextlib import closing
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn
from weakref import WeakKeyDictionary

import httpx
from pydantic import BaseModel, ConfigDict, Field

from mcp_unifi.clients.errors import ControllerScopeDenied
from mcp_unifi.clients.errors import DiagnosticError as UniFiError
from mcp_unifi.redaction import scrub


@dataclass
class Operation:
    principal: str | None
    tool: str
    arguments: dict[str, Any]
    attempts: dict[tuple[Authority, str, str], str] = field(default_factory=dict)
    scope_denial: ControllerScopeDenied | None = None


OPERATION: ContextVar[Operation | None] = ContextVar("unifi_operation", default=None)


def principal() -> str | None:
    from fastmcp.server.dependencies import get_access_token, get_http_request

    try:
        token = get_access_token()
    except Exception:
        token = None
    if token is not None:
        return token.client_id
    try:
        get_http_request()
    except RuntimeError:
        return os.environ.get("MCP_UNIFI_STDIO_PRINCIPAL")
    return None


class OperatorGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: int = Field(ge=2, le=2)
    journal_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    id: str = Field(min_length=1, max_length=128)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    principal: str = Field(min_length=1, max_length=256)
    controller: str
    site: str
    expires: float


def intent_digest(
    identity: str, controller: str, site: str, tool: str, arguments: dict[str, Any]
) -> str:
    arguments = dict(arguments)
    if "controller" in arguments:
        arguments["controller"] = controller
    value = {
        "version": 1,
        "principal": identity,
        "controller": controller,
        "site": site,
        "tool": tool,
        "arguments": arguments,
    }
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def secure_path(path: Path, *, directory: bool = False) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or info.st_mode & 0o077:
        raise UniFiError("Approval and journal paths require owner-only permissions.")
    if info.st_uid != os.getuid():
        raise UniFiError("Approval and journal paths must belong to the service user.")
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise UniFiError("Invalid approval or journal path type.")


ATTEMPTS_SCHEMA = (
    "CREATE TABLE attempts (grant_id TEXT PRIMARY KEY, digest TEXT, intent TEXT, "
    "created REAL, outcome TEXT)"
)
META_SCHEMA = (
    "CREATE TABLE journal_meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
    "version INTEGER NOT NULL, journal_id TEXT NOT NULL)"
)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def initialize_journal(path: Path) -> str:
    path = path.absolute()
    secure_path(path.parent, directory=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    identity = os.fstat(descriptor)
    os.close(descriptor)
    generation = uuid.uuid4().hex
    secure_path(path)
    current = path.stat()
    if (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
        raise UniFiError("Mutation journal changed during initialization.")
    with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)) as connection, connection:
        connection.execute("PRAGMA synchronous=EXTRA")
        connection.execute("PRAGMA fullfsync=ON")
        current = path.stat()
        if (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
            raise UniFiError("Mutation journal changed during initialization.")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(ATTEMPTS_SCHEMA)
        connection.execute(META_SCHEMA)
        connection.execute("INSERT INTO journal_meta VALUES (1, 2, ?)", (generation,))
    secure_path(path)
    current = path.stat()
    if (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
        raise UniFiError("Mutation journal changed during initialization.")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        current = os.fstat(descriptor)
        if (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
            raise UniFiError("Mutation journal changed during initialization.")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _sync_directory(path.parent)
    return generation


class _GrantRefused(UniFiError):
    pass


class Authority:
    def __init__(
        self,
        *,
        readonly: bool,
        scopes: dict[str, list[str]],
        grants: Path | None,
        journal: Path | None,
    ) -> None:
        self.readonly = readonly
        self.scopes = scopes
        self.grants = grants
        self.journal = journal
        self.healthy = True
        self._journal_identity: tuple[int, int, str] | None = None

    def check_scope(self, controller: str) -> None:
        if self.scopes and controller not in self.scopes.get(principal() or "", []):
            self._refuse_scope("Caller is not authorized for this controller.")

    def _refuse_scope(self, message: str) -> NoReturn:
        denial = ControllerScopeDenied(message)
        operation = OPERATION.get()
        if operation is not None:
            operation.scope_denial = denial
        raise denial

    def _check_identity(
        self, generation: str, connection: sqlite3.Connection | None = None
    ) -> None:
        if self.journal is None:
            raise UniFiError("A durable mutation journal is required.")
        secure_path(self.journal.parent, directory=True)
        secure_path(self.journal)
        if connection is not None and connection.execute(
            "SELECT singleton,version,journal_id FROM journal_meta"
        ).fetchall() != [(1, 2, generation)]:
            raise UniFiError("Mutation journal generation changed.")
        info = self.journal.stat()
        identity = (info.st_dev, info.st_ino, generation)
        if self._journal_identity is not None and identity != self._journal_identity:
            raise UniFiError("Mutation journal identity changed.")

    def _connection(self) -> sqlite3.Connection:
        connection = None
        try:
            if self.journal is None:
                raise UniFiError("A durable mutation journal is required.")
            secure_path(self.journal.parent, directory=True)
            secure_path(self.journal)
            before = self.journal.stat()
            connection = sqlite3.connect(
                self.journal.absolute().as_uri() + "?mode=rw", uri=True, timeout=10
            )
            connection.execute("PRAGMA synchronous=EXTRA")
            connection.execute("PRAGMA fullfsync=ON")
            schema = dict(
                connection.execute("SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL")
            )
            if schema != {"attempts": ATTEMPTS_SCHEMA, "journal_meta": META_SCHEMA}:
                raise UniFiError("Invalid mutation journal schema.")
            rows = connection.execute(
                "SELECT singleton,version,journal_id FROM journal_meta"
            ).fetchall()
            if len(rows) != 1 or rows[0][:2] != (1, 2):
                raise UniFiError("Invalid mutation journal metadata.")
            generation = rows[0][2]
            if (
                not isinstance(generation, str)
                or len(generation) != 32
                or any(c not in "0123456789abcdef" for c in generation)
            ):
                raise UniFiError("Invalid mutation journal generation.")
            self._check_identity(generation)
            after = self.journal.stat()
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise UniFiError("Mutation journal changed during open.")
            if self._journal_identity is None:
                self._journal_identity = (after.st_dev, after.st_ino, generation)
            _sync_directory(self.journal.parent)
            return connection
        except (OSError, sqlite3.Error, UniFiError) as exc:
            if connection is not None:
                connection.close()
            self.healthy = False
            raise UniFiError("Mutation journal is unavailable or invalid.") from exc

    def journal_id(self) -> str:
        if not self.healthy:
            raise UniFiError("Mutation approval or durable audit is unavailable.")
        with closing(self._connection()):
            assert self._journal_identity is not None
            return self._journal_identity[2]

    async def begin(self, controller: str, site: str) -> None:
        self.check_scope(controller)
        operation = OPERATION.get()
        if self.readonly or operation is None or not operation.principal:
            raise UniFiError("Real writes require writable mode and a trusted caller identity.")
        if not self.healthy or self.grants is None:
            raise UniFiError("Mutation approval or durable audit is unavailable.")
        if controller not in self.scopes.get(operation.principal, []):
            self._refuse_scope("Writable callers require an explicit controller scope.")
        generation = self.journal_id()
        key = (self, controller, site)
        if key in operation.attempts:
            try:
                with closing(self._connection()) as connection, connection:
                    connection.execute("BEGIN IMMEDIATE")
                    self._check_identity(generation, connection)
                    row = connection.execute(
                        "SELECT outcome FROM attempts WHERE grant_id=?", (operation.attempts[key],)
                    ).fetchone()
                    if row != ("pending",):
                        raise UniFiError("Pending mutation journal state is missing.")
                    self._check_identity(generation, connection)
                self._check_identity(generation)
            except (OSError, sqlite3.Error, UniFiError) as exc:
                self.healthy = False
                raise UniFiError(
                    "Mutation journal continuation failed. No controller write was made."
                ) from exc
            return
        digest = intent_digest(
            operation.principal, controller, site, operation.tool, operation.arguments
        )
        secure_path(self.grants, directory=True)
        matches: list[OperatorGrant] = []
        for path in sorted(self.grants.glob("*.json")):
            secure_path(path)
            try:
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(descriptor) as file:
                    grant = OperatorGrant.model_validate_json(file.read(16385))
            except (OSError, ValueError) as exc:
                raise UniFiError("Invalid operator grant file.") from exc
            if (
                grant.journal_id == generation
                and grant.digest == digest
                and grant.principal == operation.principal
                and grant.controller == controller
                and grant.site == site
                and math.isfinite(grant.expires)
                and time.time() < grant.expires <= time.time() + 3600
            ):
                matches.append(grant)
        if not matches:
            raise UniFiError("No exact unexpired operator grant authorizes this operation.")
        from mcp_unifi import audit

        await audit.get_audit_log().emit(
            controller=controller,
            tool=operation.tool,
            args=operation.arguments,
            result={"phase": "intent"},
            success=False,
            latency_ms=0,
            client_id=operation.principal,
        )
        if not self.healthy:
            raise UniFiError("Mutation approval or durable audit is unavailable.")
        if not audit.get_audit_log().healthy:
            raise UniFiError("Audit is unhealthy. No controller write was made.")
        if all(time.time() >= grant.expires for grant in matches):
            raise UniFiError("Operator grant expired before durable consumption.")
        try:
            with closing(self._connection()) as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                self._check_identity(generation, connection)
                selected_grant = next(
                    (
                        candidate
                        for candidate in matches
                        if time.time() < candidate.expires
                        and connection.execute(
                            "SELECT 1 FROM attempts WHERE grant_id=?", (candidate.id,)
                        ).fetchone()
                        is None
                    ),
                    None,
                )
                if selected_grant is None:
                    raise _GrantRefused("Operator grant has already been consumed or expired.")
                grant = selected_grant
                if time.time() >= grant.expires:
                    raise _GrantRefused("Operator grant expired before durable consumption.")
                connection.execute(
                    "INSERT INTO attempts VALUES (?, ?, ?, ?, ?)",
                    (
                        grant.id,
                        digest,
                        json.dumps(
                            scrub(
                                {
                                    "tool": operation.tool,
                                    "principal": operation.principal,
                                    "controller": controller,
                                    "site": site,
                                    "arguments": operation.arguments,
                                }
                            )
                        ),
                        time.time(),
                        "pending",
                    ),
                )
                self._check_identity(generation, connection)
            self._check_identity(generation)
        except _GrantRefused:
            raise
        except (OSError, sqlite3.Error, UniFiError, ValueError) as exc:
            self.healthy = False
            raise UniFiError(
                "Durable prewrite audit failed. No controller write was made."
            ) from exc
        operation.attempts[key] = grant.id

    def _record_outcome(self, grant_id: str, outcome: str) -> None:
        with closing(self._connection()) as connection, connection:
            assert self._journal_identity is not None
            generation = self._journal_identity[2]
            connection.execute("BEGIN IMMEDIATE")
            self._check_identity(generation, connection)
            cursor = connection.execute(
                "UPDATE attempts SET outcome=? WHERE grant_id=? AND outcome='pending'",
                (outcome, grant_id),
            )
            if cursor.rowcount != 1:
                raise UniFiError("Missing pending mutation journal outcome.")
            self._check_identity(generation, connection)
        self._check_identity(generation)

    def complete(self, operation: Operation, outcome: str) -> None:
        from mcp_unifi import audit

        for (owner, _controller, _site), grant_id in operation.attempts.items():
            if owner is not self:
                continue
            try:
                if not self.healthy or not audit.get_audit_log().healthy:
                    raise UniFiError("Audit completion failed.")
                self._record_outcome(grant_id, outcome)
            except (OSError, sqlite3.Error, UniFiError) as exc:
                self.healthy = False
                raise UniFiError(
                    "Controller outcome is uncertain because audit completion failed."
                ) from exc

    def try_record_uncertain_outcome(self, operation: Operation) -> None:
        for (owner, _controller, _site), grant_id in operation.attempts.items():
            if owner is not self:
                continue
            try:
                self._record_outcome(grant_id, "uncertain")
            except (OSError, sqlite3.Error, UniFiError):
                self.healthy = False


@dataclass(frozen=True)
class Target:
    authority: Authority
    controller: str
    site: str


CLIENTS: WeakKeyDictionary[httpx.AsyncClient, Target] = WeakKeyDictionary()


async def before_request(client: httpx.AsyncClient, method: str, url: str) -> None:
    if method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    path = httpx.URL(url).path
    if (
        method.upper() == "POST"
        and "/proxy/network/api/s/" in path
        and path.endswith("/stat/session")
    ):
        return
    target = CLIENTS.get(client)
    if isinstance(client._transport_for_url(httpx.URL(url)), httpx.MockTransport):
        if target is not None:
            target.authority.check_scope(target.controller)
            if target.authority.readonly:
                raise UniFiError("Real client is read-only.")
        return
    if target is None:
        raise UniFiError("Real mutation client is not registered with the authorization boundary.")
    await target.authority.begin(target.controller, target.site)
