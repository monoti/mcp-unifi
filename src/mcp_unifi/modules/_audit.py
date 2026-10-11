"""Tool classification, trusted effective intent, audit and outcome recording.

Real mutations cross the request guard in authority.py. This decorator captures
validated arguments with defaults before execution and records whether the
returned result succeeded. Failed persistence blocks later mutations.
"""

from __future__ import annotations

import copy
import inspect
import json
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from mcp_unifi import audit, telemetry
from mcp_unifi.authority import OPERATION, Operation, principal
from mcp_unifi.clients.errors import safe_error

P = ParamSpec("P")
R = TypeVar("R")

#: ``{tool_name: mutates}`` for every tool decorated with :func:`audited`.
#: Populated at decoration time (i.e. when a module's ``register()`` runs).
_CLASSIFICATION: dict[str, bool] = {}


class ToolClassificationConflictError(ValueError):
    """Raised when one tool name is declared with two different ``mutates`` values.

    Tool names are globally unique across modules, so two conflicting
    declarations mean either a copy-paste error or a genuine name collision.
    Either way the write gate could not answer "is this tool mutating?"
    deterministically, so we refuse at registration rather than pick one.
    """


def tool_mutates(tool_name: str) -> bool | None:
    """Return the declared ``mutates`` flag for ``tool_name``, or ``None``.

    ``None`` means "never classified" and is treated as a hard error by
    :func:`mcp_unifi.dispatcher.register_modules` — never as "read-only".
    """
    return _CLASSIFICATION.get(tool_name)


def classified_tools() -> dict[str, bool]:
    """Return a copy of the whole ``{tool_name: mutates}`` registry."""
    return dict(_CLASSIFICATION)


_ANNOTATIONS: ContextVar[dict[str, Any] | None] = ContextVar(
    "mcp_unifi_audit_annotations", default=None
)


def annotate_audit(*, controller: str | None = None, **fields: Any) -> None:
    """Correct or enrich the audit event for the tool call in progress.

    The decorator reads ``controller`` from the tool's kwargs, which is right
    for every tool that takes one. ``confirm_destructive_action`` takes only a
    token, so its event said ``default`` no matter which controller the queued
    action targeted. A tool body calls this with the controller it actually
    resolved, plus any non-secret fields that belong in ``args`` (a
    ``preview_id`` that links a confirm to its preview, the queued ``action``).
    Values here go through the same scrub as kwargs, so a sensitive key is
    still redacted. No-op outside an audited call.
    """
    current = _ANNOTATIONS.get()
    if current is None:
        return
    if controller is not None:
        current["controller"] = controller
    current.setdefault("args", {}).update(fields)


def _current_client_id() -> str | None:
    """Return the authenticated client_id for the current request, or None.

    Falls back to None on stdio, in tests without an MCP context, or when
    auth is disabled. Never raises — audit must work even if the FastMCP
    dependency surface changes shape across versions.
    """
    try:
        from fastmcp.server.dependencies import get_access_token

        token = get_access_token()
    except Exception:
        return None
    return token.client_id if token is not None else None


def _coerce_result(value: Any) -> Any:
    """Best-effort decode of a tool's return value into a structured object.

    Tools return JSON strings (via :func:`format_json`). We parse them back so
    the audit log holds dicts/lists, not stringified payloads. Anything we
    cannot parse is recorded as-is.
    """
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value
    return value


def audited(
    tool_name: str,
    *,
    mutates: bool,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Wrap an async tool function so every call emits an audit event.

    Args:
        tool_name: The MCP tool name as registered with FastMCP. Must match
            the function name (or ``@mcp.tool(name=...)`` override) so audit
            log lines line up with what a caller actually invoked.
        mutates: Required. ``True`` when calling the tool changes state outside
            this process — controller configuration, device state (an LED, a
            reboot, a deauth), or controller-side work (a speed test). ``False``
            only when the tool is a pure read: it may call the controller, but
            leaves it exactly as it found it. Read the tool's ``Side effects:``
            docstring section and make them agree. Tools declared ``True`` are
            hidden and refused when ``MCP_UNIFI_READONLY=true``.

    The wrapped function preserves its original signature, so FastMCP's schema
    introspection sees the same parameters it would for the bare function.
    """
    previous = _CLASSIFICATION.get(tool_name)
    if previous is not None and previous != mutates:
        raise ToolClassificationConflictError(
            f"tool {tool_name!r} was declared with mutates={previous} and again "
            f"with mutates={mutates}. Tool names must be globally unique and "
            f"carry one classification."
        )
    _CLASSIFICATION[tool_name] = mutates

    def decorator(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            # Tools are always invoked with kwargs from FastMCP's JSON
            # dispatch. Defensive: if any positional args slip through, capture
            # them under a synthetic key so they aren't silently dropped from
            # the audit envelope.
            bound = inspect.signature(fn).bind(*args, **kwargs)
            bound.apply_defaults()
            operation = Operation(principal(), tool_name, copy.deepcopy(dict(bound.arguments)))
            operation_token = OPERATION.set(operation)
            audit_args: dict[str, Any] = dict(kwargs)
            if args:
                audit_args["_positional"] = list(args)

            controller = str(kwargs.get("controller", "default"))
            client_id = _current_client_id()
            log = audit.get_audit_log()
            annotations: dict[str, Any] = {}
            annotations_token = _ANNOTATIONS.set(annotations)

            def _apply_annotations() -> None:
                nonlocal controller
                controller = str(annotations.get("controller", controller))
                audit_args.update(annotations.get("args", {}))

            # The span wraps the audit emit as well as the tool body, so its
            # duration is the full cost of serving the call rather than just
            # the controller round trip. That is the number an SLO is written
            # against: a caller waits for both.
            with telemetry.tool_span(
                tool_name,
                mutates=mutates,
                controller=controller,
                client_id=client_id,
                dry_run=telemetry.coerce_dry_run(kwargs.get("dry_run")),
            ) as span:
                start = time.perf_counter()
                try:
                    result = await fn(*args, **kwargs)
                except BaseException as exc:
                    OPERATION.reset(operation_token)
                    _ANNOTATIONS.reset(annotations_token)
                    _apply_annotations()
                    latency_ms = (time.perf_counter() - start) * 1000.0
                    span.record_error(exc)
                    await log.emit(
                        controller=controller,
                        tool=tool_name,
                        args=audit_args,
                        result=None,
                        success=False,
                        latency_ms=latency_ms,
                        error=safe_error(exc) if isinstance(exc, Exception) else "Call cancelled.",
                        client_id=client_id,
                    )
                    for authority, _controller, _site in operation.attempts:
                        authority.complete(operation, "uncertain")
                    raise

                OPERATION.reset(operation_token)
                _ANNOTATIONS.reset(annotations_token)
                _apply_annotations()
                latency_ms = (time.perf_counter() - start) * 1000.0
                decoded = _coerce_result(result)
                span.set(
                    telemetry.ATTR_OUTCOME,
                    telemetry.OUTCOME_ERROR
                    if isinstance(decoded, dict) and decoded.get("error")
                    else telemetry.OUTCOME_OK,
                )
                await log.emit(
                    controller=controller,
                    tool=tool_name,
                    args=audit_args,
                    result=_coerce_result(result),
                    success=not (isinstance(decoded, dict) and bool(decoded.get("error"))),
                    latency_ms=latency_ms,
                    client_id=client_id,
                )
                for authority, _controller, _site in operation.attempts:
                    authority.complete(
                        operation,
                        "error"
                        if isinstance(decoded, dict) and decoded.get("error")
                        else "success",
                    )
                return result

        return wrapper

    return decorator


__all__ = [
    "ToolClassificationConflictError",
    "annotate_audit",
    "audited",
    "classified_tools",
    "tool_mutates",
]
