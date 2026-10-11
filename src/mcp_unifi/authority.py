"""Operator grants and the durable boundary before real controller writes."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import stat
import time
from contextlib import closing
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from weakref import WeakKeyDictionary

import httpx
from pydantic import BaseModel, ConfigDict, Field

from mcp_unifi.clients.errors import DiagnosticError as UniFiError
from mcp_unifi.redaction import scrub


@dataclass
class Operation:
    principal: str | None
    tool: str
    arguments: dict[str, Any]
    attempts: dict[tuple[Authority, str, str], str] = field(default_factory=dict)


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

    version: int = Field(ge=1, le=1)
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
    if directory != stat.S_ISDIR(info.st_mode):
        raise UniFiError("Invalid approval or journal path type.")


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

    def check_scope(self, controller: str) -> None:
        if self.scopes and controller not in self.scopes.get(principal() or "", []):
            raise UniFiError("Caller is not authorized for this controller.")

    def _connection(self) -> sqlite3.Connection:
        if self.journal is None:
            raise UniFiError("A durable mutation journal is required.")
        secure_path(self.journal.parent, directory=True)
        if not self.journal.exists():
            try:
                descriptor = os.open(self.journal, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
        secure_path(self.journal)
        connection = sqlite3.connect(self.journal, timeout=10)
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS attempts "
            "(grant_id TEXT PRIMARY KEY, digest TEXT, intent TEXT, "
            "created REAL, outcome TEXT)"
        )
        connection.commit()
        return connection

    async def begin(self, controller: str, site: str) -> None:
        self.check_scope(controller)
        operation = OPERATION.get()
        if self.readonly or operation is None or not operation.principal:
            raise UniFiError("Real writes require writable mode and a trusted caller identity.")
        if not self.healthy or self.grants is None:
            raise UniFiError("Mutation approval or durable audit is unavailable.")
        if controller not in self.scopes.get(operation.principal, []):
            raise UniFiError("Writable callers require an explicit controller scope.")
        key = (self, controller, site)
        if key in operation.attempts:
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
                grant.digest == digest
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
        if not audit.get_audit_log().healthy:
            raise UniFiError("Audit is unhealthy. No controller write was made.")
        grant = matches[0]
        if time.time() >= grant.expires:
            raise UniFiError("Operator grant expired before durable consumption.")
        try:
            with closing(self._connection()) as connection, connection:
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
        except sqlite3.IntegrityError as exc:
            raise UniFiError("Operator grant has already been consumed.") from exc
        except (OSError, sqlite3.Error) as exc:
            self.healthy = False
            raise UniFiError(
                "Durable prewrite audit failed. No controller write was made."
            ) from exc
        operation.attempts[key] = grant.id

    def complete(self, operation: Operation, outcome: str) -> None:
        from mcp_unifi import audit

        for (owner, _controller, _site), grant_id in operation.attempts.items():
            if owner is not self:
                continue
            if not audit.get_audit_log().healthy:
                self.healthy = False
                raise UniFiError("Controller outcome is uncertain because audit completion failed.")
            try:
                with closing(self._connection()) as connection, connection:
                    connection.execute(
                        "UPDATE attempts SET outcome=? WHERE grant_id=?", (outcome, grant_id)
                    )
            except (OSError, sqlite3.Error, UniFiError) as exc:
                self.healthy = False
                raise UniFiError(
                    "Controller outcome is uncertain because audit completion failed."
                ) from exc


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
