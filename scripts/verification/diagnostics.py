import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]) / "src"))

from mcp_unifi.audit import AuditLog
from mcp_unifi.clients.errors import UniFiError, safe_error
from mcp_unifi.logging_setup import JsonFormatter, SafeTextFormatter

SENTINEL = "synthetic-diagnostics-only-83d80c"


class MemorySink:
    def __init__(self):
        self.events = []

    async def write(self, event):
        self.events.append(event)

    async def aclose(self):
        return None


async def probe():
    flags = {}
    formats = {"json": JsonFormatter(), "text": SafeTextFormatter()}
    for name, formatter in formats.items():
        for shape, args in (
            ("mapping", ({"password": SENTINEL},)),
            ("serialized", (json.dumps({"password": SENTINEL}),)),
        ):
            record = logging.LogRecord("probe", logging.WARNING, __file__, 1, "%s", args, None)
            flags[f"{name}_{shape}_contains_secret"] = SENTINEL in formatter.format(record)
        try:
            try:
                raise RuntimeError(SENTINEL)
            except RuntimeError as cause:
                raise UniFiError(SENTINEL) from cause
        except UniFiError:
            record = logging.LogRecord(
                "probe", logging.ERROR, __file__, 1, "operation failed", (), sys.exc_info()
            )
            flags[f"{name}_chained_contains_secret"] = SENTINEL in formatter.format(record)
    flags["unexpected_domain_error_contains_secret"] = SENTINEL in safe_error(UniFiError(SENTINEL))
    sink = MemorySink()
    audit = AuditLog(sink)
    await audit.emit("default", "synthetic", {}, None, False, 0, error=SENTINEL)
    flags["audit_error_contains_secret"] = SENTINEL in sink.events[0].to_json()
    print(json.dumps(flags, indent=2, sort_keys=True))
    assert not any(flags.values()), "A diagnostics path exposed the synthetic secret"


asyncio.run(probe())
