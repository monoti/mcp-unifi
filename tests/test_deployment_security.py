import os
import stat
from pathlib import Path

import pytest
import yaml

from mcp_unifi.authority import secure_path
from mcp_unifi.clients.errors import UniFiError

ROOT = Path(__file__).resolve().parents[1]


def test_compose_contains_local_build_loopback_and_writable_audit_volume():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    service = compose["services"]["mcp-unifi"]
    assert service["build"] == "."
    assert service["image"].startswith("mcp-unifi-hardening:")
    assert service["ports"] == ["127.0.0.1:${MCP_PORT:-3714}:${MCP_PORT:-3714}"]
    assert service["read_only"] is True
    assert service["environment"]["MCP_UNIFI_READONLY"] == "true"
    assert service["environment"]["UNIFI_VERIFY_SSL"] == "true"
    assert "mcp-unifi-audit:/var/lib/mcp-unifi" in service["volumes"]
    assert service["environment"]["MCP_UNIFI_AUDIT_PATH"].startswith("/var/lib/mcp-unifi/private/")


def test_helm_safe_defaults_and_audit_readiness():
    values = yaml.safe_load((ROOT / "charts/mcp-unifi/values.yaml").read_text())
    assert values["unifi"]["verifySSL"] is True
    assert values["readOnly"] is True
    assert values["auth"]["required"] is True
    assert values["readinessProbe"]["httpGet"]["path"] == "/ready"
    assert values["image"]["repository"] == "mcp-unifi-hardening"
    assert values["securityContext"]["readOnlyRootFilesystem"] is True
    assert "fsGroup" not in values["podSecurityContext"]


def test_all_enabled_release_publishers_depend_on_exact_revision_ci():
    directory = ROOT / ".github/workflows"
    ci = yaml.safe_load((directory / "ci.yml").read_text())
    assert "workflow_call" in ci.get("on", ci.get(True))
    assert "github.workflow" in ci["concurrency"]["group"]
    assert {"lint-and-type", "test", "build-and-scan"} <= ci["jobs"].keys()
    for name, publication in [
        ("release.yml", "publish"),
        ("helm-release.yml", "release-chart"),
        ("docs.yml", "build-and-deploy"),
    ]:
        workflow = yaml.safe_load((directory / name).read_text())
        assert workflow["jobs"]["verify"]["uses"] == "./.github/workflows/ci.yml"
        assert workflow["jobs"][publication]["needs"] == "verify"
    registry = yaml.safe_load((directory / "publish-mcp.yml").read_text())
    assert set(registry["jobs"]) == {"publication-disabled"}
    assert registry["permissions"] == {"contents": "read"}


def test_kubernetes_permission_rewriting_rejects_private_grants(tmp_path):
    directory = tmp_path / "approvals"
    directory.mkdir(mode=0o700)
    grant = directory / "grant.json"
    grant.touch(mode=0o600)
    secure_path(directory, directory=True)
    secure_path(grant, directory=False)
    group_read_only = stat.S_IMODE(directory.stat().st_mode) | stat.S_IRGRP | stat.S_IXGRP
    os.chmod(directory, group_read_only | stat.S_ISGID)
    os.chmod(grant, 0o640)
    with pytest.raises(UniFiError):
        secure_path(directory, directory=True)
    with pytest.raises(UniFiError):
        secure_path(grant, directory=False)
