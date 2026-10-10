import json
import logging

import httpx
import pytest
import respx

from mcp_unifi.clients.access import AccessClient
from mcp_unifi.clients.protect import ProtectClient
from mcp_unifi.clients.unifi import UniFiClient, UniFiError
from mcp_unifi.logging_setup import JsonFormatter, SafeTextFormatter
from mcp_unifi.redaction import scrub


@pytest.mark.parametrize(
    "client_type,prefix",
    [
        (UniFiClient, "/proxy/network"),
        (ProtectClient, "/proxy/protect/api"),
        (AccessClient, "/proxy/access/api/v2"),
    ],
)
@pytest.mark.parametrize(
    "body",
    [
        '{"message":"synthetic-secret"}',
        '{"meta":{"msg":"synthetic-secret"}}',
        "synthetic-secret",
    ],
)
@respx.mock
async def test_controller_prose_never_enters_exception(client_type, prefix, body):
    respx.get(f"https://gateway.test:443{prefix}/probe").mock(
        return_value=httpx.Response(400, text=body)
    )
    client = client_type(host="gateway.test", api_key="synthetic", port=443)
    try:
        with pytest.raises(UniFiError) as caught:
            await client._request("GET", "/probe")
        assert "synthetic-secret" not in str(caught.value)
        assert "400" in str(caught.value)
    finally:
        await client.aclose()


def test_backup_audit_omits_opaque_scalar_and_structured_values():
    for value in ['{"nested":"synthetic-secret"}', {"nested": "synthetic-secret"}]:
        assert "synthetic-secret" not in json.dumps(scrub({"backup_json": value}))


@pytest.mark.parametrize("formatter", [JsonFormatter(), SafeTextFormatter()])
def test_logs_omit_exception_and_chained_cause(formatter):
    try:
        try:
            raise ValueError("synthetic-cause-secret")
        except ValueError as cause:
            raise RuntimeError("synthetic-error-secret") from cause
    except RuntimeError:
        import sys

        record = logging.LogRecord("test", 40, __file__, 1, "operation failed", (), sys.exc_info())
    formatted = formatter.format(record)
    assert "synthetic-cause-secret" not in formatted
    assert "synthetic-error-secret" not in formatted
