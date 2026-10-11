import json
import logging

import httpx
import pytest
import respx

from mcp_unifi.clients.access import AccessClient
from mcp_unifi.clients.errors import safe_error
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


@pytest.mark.parametrize("formatter", [JsonFormatter(), SafeTextFormatter()])
@pytest.mark.parametrize(
    "value", [{"password": "synthetic-secret"}, '{"password":"synthetic-secret"}']
)
def test_logs_scrub_formatted_structured_arguments(formatter, value):
    record = logging.LogRecord("test", 30, __file__, 1, "%s", (value,), None)
    assert "synthetic-secret" not in formatter.format(record)


def test_unknown_domain_error_message_is_not_trusted():
    assert "synthetic-secret" not in safe_error(UniFiError("synthetic-secret"))


@respx.mock
async def test_binary_and_v2_errors_omit_controller_prose():
    network = UniFiClient("gateway.test", "synthetic")
    protect = ProtectClient("gateway.test", "synthetic")
    respx.get("https://gateway.test:443/proxy/network/v2/api/site/default/trafficrules").mock(
        return_value=httpx.Response(400, text="synthetic-secret")
    )
    respx.get("https://gateway.test:443/proxy/protect/api/probe").mock(
        return_value=httpx.Response(400, content=b"synthetic-secret")
    )
    try:
        for call in [
            network._v2_request("GET", "/trafficrules"),
            protect._request_bytes("GET", "/probe"),
        ]:
            with pytest.raises(UniFiError) as caught:
                await call
            assert "synthetic-secret" not in str(caught.value)
    finally:
        await network.aclose()
        await protect.aclose()


async def test_refused_restore_does_not_audit_opaque_secrets(tmp_path):
    from mcp_unifi import audit
    from mcp_unifi.config import Settings
    from mcp_unifi.server import build_server

    path = tmp_path / "audit.jsonl"
    audit.set_audit_log(audit.AuditLog(audit.FileSink(path)))
    server = build_server(Settings(stub_mode=True, readonly=True))
    result = await server.call_tool(
        "restore_config", {"backup_json": '{"password":"synthetic-secret"}'}
    )
    assert "read-only" in result.content[0].text
    assert "synthetic-secret" not in path.read_text()
