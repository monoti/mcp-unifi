# mcp-unifi

<!-- mcp-name: io.github.monoti/unifi -->

**Safety-first MCP server for self-hosted UniFi. Dry-run previews, JSONL audit log, composite rollback. Network + Protect + Access.**

[![CI](https://github.com/monoti/mcp-unifi/actions/workflows/ci.yml/badge.svg)](https://github.com/monoti/mcp-unifi/actions/workflows/ci.yml)
[![MCP](https://img.shields.io/badge/MCP-stdio%20%2B%20Streamable%20HTTP-brightgreen.svg)](https://modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An [MCP server](https://modelcontextprotocol.io/) built around the assumption that LLM-driven infrastructure calls need guardrails. Every destructive tool accepts `dry_run=True` and returns the predicted change set without writing. Composite tools (`create_iot_network`, `create_guest_network`, `provision_homelab_service`, `provision_camera`) capture pre-state and roll back applied steps on partial failure. Calls produce sanitized JSONL records when the sink is healthy. Real mutations fail closed on audit or journal failure; the included `mcp-unifi-replay` CLI can re-issue a log against a fresh controller.

Beyond the safety substrate: **Network** tools for devices, AP radio tuning, VLANs, WLANs, firewall, switch ports, port forwards, DHCP reservations, AP groups, observability, Threat Management / IDS-IPS, Honeypot, and Teleport VPN, plus opt-in **Protect** (cameras, motion events, smart detections, recording config) and **Access** (doors, credentials, visitors, badge events, hubs / readers). Every tool accepts a `controller` parameter so one server instance manages multiple UniFi sites. Speaks both **stdio** (Claude Desktop, `uvx`, `.dxt`) and **Streamable HTTP** (Docker, Helm). The full, always-current tool list is in the auto-generated [Tool Manifest](https://pete-builds.github.io/mcp-unifi/tools/). Upstream reports support for UniFi OS gateways running UniFi Network 9.x or newer (UDM, UDM Pro, UDM SE, UCG-Fiber, UCG-Ultra, UDR, UDW, UniFi OS Server), authenticated with a local API key from Settings → Control Plane → Integrations. Upstream reports verification against a UCG-Fiber on UniFi OS 5.1.33 running UniFi Network 10.6.101 (2026-09-13). Firewall reads cover both the legacy rulesets (`list_firewall_rules`) and the Zone-Based Firewall (`list_firewall_policies`, `list_firewall_zones`), and `audit_open_ports` checks both, so a site that has migrated to zones is not reported as having no firewall. Firewall writes (`create_firewall_rule` and friends) still target the legacy `/rest/firewallrule` API and do not create zone policies. No Site Manager or cloud account required.

## Install and operate this fork

Build this checkout. The hardened fork has not published a Docker image, DXT release, or MCP Registry entry. Upstream packages do not contain these changes.

```sh
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements-build.lock -r requirements.lock
.venv/bin/pip install --no-deps --no-build-isolation .
STUB_MODE=true .venv/bin/mcp-unifi
```

The default transport is stdio. Read-only mode and verified controller TLS are enabled by default. Real writes require an exact operator-issued grant, a trusted identity with controller scope, and durable audit and replay storage. A model-supplied confirmation token alone cannot authorize a controller mutation.

Read [Operating the hardened fork](docs/hardening-operations.md) for real-controller setup, external approval commands, filesystem ownership, local Docker/Helm builds, HTTP authentication, and migration requirements. The [finding-to-test map](docs/security-findings.md) records the evidence and its limits.

## Configuration

All config is read from environment variables (and `.env` when present). The six most common:

| Variable | Default | Notes |
|---|---|---|
| `STUB_MODE` | `true` | When `false`, real-mode controller config is required. |
| `UNIFI_HOST` | (empty) | Gateway IP or hostname. Required in real mode. |
| `UNIFI_API_KEY` | (empty) | Local API key. Required in real mode. |
| `MCP_UNIFI_READONLY` | `true` | When `true`, mutating tools are hidden and refused. See the [Security guide](https://pete-builds.github.io/mcp-unifi/guides/security/#read-only-mode). |
| `MCP_UNIFI_MODULES_ENABLED` | `network` | Set to `network,protect,access` to enable all three modules. |
| `MCP_UNIFI_CONTROLLERS_FILE` | (unset) | YAML file with named controllers for multi-site. |
| `MCP_UNIFI_OTEL_ENABLED` | `false` | Optional OpenTelemetry tracing, one span per tool call. Off by default and the SDK is not a dependency. See [Operations](docs/operations.md). |
| `UNIFI_API_KEY_FILE` | (unset) | Read the API key from a file (a Docker or Kubernetes secret mount) instead of `UNIFI_API_KEY`. Wins if both are set. TLS verification defaults to on for both forms. |
| `UNIFI_ACCESS_API_KEY_FILE` | (unset) | File-backed form of `UNIFI_ACCESS_API_KEY`. |
| `UNIFI_OS_PASSWORD_FILE` | (unset) | File-backed form of `UNIFI_OS_PASSWORD`. |
| `MCP_UNIFI_AUTH_TOKEN_FILE` | (unset) | File holding one bearer token (or the full `MCP_UNIFI_AUTH_TOKENS` grammar). Adds to whatever `MCP_UNIFI_AUTH_TOKENS` defines. |
| `MCP_UNIFI_CLIENT_ID` | (unset) | Client name for the bare token in `MCP_UNIFI_AUTH_TOKEN_FILE`. |
| `UNIFI_PINNED_CERT` | (unset) | Path to the console's own certificate (PEM) from `mcp-unifi-pin-cert`. When set, that certificate is the only one the server will accept from this controller. See below. |

Full env var reference and the multi-site YAML schema are in the [Configuration docs](https://pete-builds.github.io/mcp-unifi/reference/configuration/).

### File-backed secrets

Every secret has a `_FILE` twin for protected Docker and Kubernetes secret mounts. Inline and file-backed credentials both verify TLS by default. A missing, empty, or unreadable secret file fails startup without exposing its contents. Historical [ADR 0007](docs/decisions/0007-hardening-is-opt-in-unless-the-hole-has-no-legitimate-configuration.md) describes upstream behavior that this fork supersedes.

### Certificate pinning

UniFi consoles present a self-signed certificate whose name list does not include the address you connect to, so a trusted CA or independently verified pin may be needed. `verify_ssl` defaults to on. Pinning closes that gap without a CA: record the console's certificate once, and from then on the server accepts that certificate and nothing else.

```bash
mcp-unifi-pin-cert 192.168.1.1 --out /etc/mcp-unifi/pins/home.pem
# prints the SHA-256 fingerprint; compare it against the console before trusting it
ssh root@192.168.1.1 'openssl x509 -in /data/unifi-core/config/unifi-core.crt -noout -fingerprint -sha256'
# the same fingerprint read on the console itself, over a channel the pin does not depend on
```

Then set `pinned_cert: /etc/mcp-unifi/pins/home.pem` on the controller in the YAML, or `UNIFI_PINNED_CERT` for the single-controller env form. A pinned controller verifies every connection against that certificate and fails closed if the console presents anything else; there is no fallback. If a firmware update regenerates the console certificate, requests fail with a message that names the re-pin command, and you re-run it with `--force` after checking the new fingerprint. The server never fetches and trusts a certificate on its own: the bootstrap is always this explicit command. Pass `--expect-fingerprint` to have it refuse a certificate that does not match what you read off the console. In the container, mount the pin read-only (the compose file shows where).

## How this is built

The engineering scaffolding around the tool surface (see the [Tool Manifest](https://pete-builds.github.io/mcp-unifi/tools/) for the current count), in case you want to know what's holding it up:

**Test discipline.** ~880 tests across unit, integration, and property-based (Hypothesis) — see `pytest --collect-only` for the current count. HTTP is mocked with respx so tests don't hit a real controller. Coverage gated at 80% branch coverage in CI; run coverage locally for the current result.

**Code quality gates.** Ruff (pycodestyle, pyflakes, isort, flake8-bugbear, pyupgrade, simplify, flake8-bandit security ruleset, comprehensions) plus mypy strict (no implicit Any, unreachable code flagged, unused ignores flagged). Pre-commit hooks run lint, format, types, and regenerate the tool manifest with a drift check, so bad code never reaches CI.

**CI pipeline (5 gated jobs).** Every PR runs lockfile-drift check → lint + type check → tests + coverage → multi-arch Docker build → Trivy filesystem and image scan (HIGH/CRITICAL fails the build). Each gates the next.

**Release pipeline.** A `git tag vX.Y.Z` push triggers a multi-arch (linux/amd64 + linux/arm64) Docker build, cosign keyless signing via sigstore OIDC, SLSA build provenance attestation, CycloneDX SBOM via Syft attached to the GitHub release, a .dxt bundle for Claude Desktop one-click install, GHCR push with `vX.Y.Z` / `X.Y` / `latest` tags, after exact-revision CI succeeds. The fork has not published these artifacts.

**Dependency hygiene.** Hash-pinned via `pip install --require-hashes`. A custom CI step verifies every pinned dep in `requirements.in` matches `requirements.lock` so no one can bump one without the other. Dependabot auto-merges safe patches. The base image is digest-pinned, not tag-pinned.

**Container hardening.** Runs as non-root UID 1000, no shell, no home directory. Read-only root filesystem enforced via Docker / Helm. `/tmp` is a 16MiB tmpfs. `no-new-privileges` set. All Linux capabilities dropped. Dedicated `/health` liveness and `/ready` audit-aware readiness endpoints keep the streamable-HTTP transport from logging 406 noise on every Docker healthcheck.

**Security posture.** Bearer-token authentication on the HTTP transport, secure by default (refuses to start without tokens). Audit log records each authenticated `client_id` per call with secret scrubbing on `api_key`, `passphrase`, `password`, `secret`, `token` substring matches. API keys wrapped in pydantic `SecretStr`. `SECURITY.md` with a private disclosure path.

**Distribution surface.** GHCR (signed multi-arch), Smithery (registered), MCP Registry (listed), Helm chart (Secret/Deployment/Service/Ingress/NetworkPolicy templates), .dxt bundle, uvx / pipx.

**Documentation discipline.** Astro Starlight site auto-deploys to GitHub Pages. The per-tool reference pages are generated from FastMCP introspection by `scripts/generate_tool_manifest.py`, and the pre-commit hook regenerates and drift-checks them so code and docs can't diverge. CHANGELOG follows Keep a Changelog format.

**Version discipline.** `pyproject.toml`, the git tag, the CHANGELOG entry, the Docker image tag, the docker-compose example, and the Helm chart `appVersion` all stay aligned because the release workflow enforces it. There is never a moment where the docs and the code disagree about what version this is.

## Development

Clone, install dev dependencies, and wire up the pre-commit hooks:

```bash
git clone https://github.com/monoti/mcp-unifi.git
cd mcp-unifi
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" pre-commit
pre-commit install
```

The pre-commit hooks run ruff (lint + format), mypy strict, and the tool
manifest generator. The manifest hook regenerates
`docs/site/src/content/docs/tools/` whenever any file under
`src/mcp_unifi/modules/` changes and fails the commit if the on-disk
manifest drifts from the registered tool surface. Run the tests with
`pytest`.

To regenerate the manifest manually:

```bash
python scripts/generate_tool_manifest.py        # write
python scripts/generate_tool_manifest.py --check  # CI-style drift check
```

## Docs

- [Docs site](https://pete-builds.github.io/mcp-unifi/)
- [Network tool reference](https://pete-builds.github.io/mcp-unifi/reference/network/)
- [Protect tool reference](https://pete-builds.github.io/mcp-unifi/reference/protect/)
- [Access tool reference](https://pete-builds.github.io/mcp-unifi/reference/access/)
- [Multi-site setup](https://pete-builds.github.io/mcp-unifi/guides/multi-site/)
- [Access setup](https://pete-builds.github.io/mcp-unifi/guides/access-setup/)
- [Dry-run and audit log](https://pete-builds.github.io/mcp-unifi/guides/dry-run-audit/)
- [Security model](https://pete-builds.github.io/mcp-unifi/guides/security/)
- [Migration from v0.x](https://pete-builds.github.io/mcp-unifi/guides/migration/)
- [Changelog](CHANGELOG.md)
- [Security policy](SECURITY.md)

## License

[MIT](LICENSE).
