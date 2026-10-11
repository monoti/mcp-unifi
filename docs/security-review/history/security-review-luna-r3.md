# Luna adversarial security review, r3

## Scope and method

Reviewed the frozen `network/mcp-unifi` checkout at `f0693d4fb6b31675abea288ef3590b3f538b9fdd` against upstream `b9870c768362d5e5b1321c7048a9fc7c035a9c59`. Read the supplied r3 prompt, review brief, selected design, recovery and implementation records, r2 reviews and triage, fix report, finding map, security-review guide, original reports, and the complete source diff with relevant surrounding call paths. The checkout was clean at the requested revision. This was a static, read-only review; I ran no tests or deployment commands and contacted no controller.

## Findings

### 1. [warning] Stdio can accept a stdout audit sink and corrupt MCP framing

**Location**: `src/mcp_unifi/server.py:112-113`; `src/mcp_unifi/audit.py:298-304`

**Finding**: The stdio safety check compares the raw `MCP_UNIFI_AUDIT_SINK` value to the exact lowercase string `"stdout"`, but sink construction strips whitespace and lowercases the value. Consequently valid normalized values such as `MCP_UNIFI_AUDIT_SINK="STDOUT"` or `" stdout "` bypass the startup refusal and still create `StdoutSink`.

**Evidence**: With `MCP_UNIFI_TRANSPORT=stdio` and either value, `build_server()` passes line 112. On the first tool audit event, `get_audit_log()` calls `_build_sink_from_env()`, which normalizes the value to `stdout` and selects `StdoutSink`. Audit JSON is then written to the same stdout stream that carries MCP protocol messages, so otherwise functional stdio sessions can be corrupted. This violates the explicit stdout-audit refusal in the selected design.

**Suggestion**: Apply the same normalization when checking the transport/sink combination, ideally through one canonical sink-name parser used by both validation and construction.

## Attention: decision-trail audit

No flags. The reviewed r3 entries distinguish the accepted targeted result from the still-running full-suite check, record the local Trivy vulnerability scan as unverified after its database download failed, and do not claim release publication or deployment. The selected transcript contains the stale-prompt correction and the fresh review dispatch; I did not count the stopped dispatch as a verdict.

## Review limits

This report does not verify the parent-owned full-suite run, local artifact scans, remote release workflows, container or Kubernetes runtime behavior, desktop installation, physical power-loss durability, or live controller compatibility and permissions. No production data or credentials were accessed.
