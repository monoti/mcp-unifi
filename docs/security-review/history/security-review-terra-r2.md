# Terra adversarial security review, r2

## Scope and method

Reviewed the frozen `network/mcp-unifi` tree at
`0813ba835910c0fc86d7a2c0e5593a9a69ae9f65` against the supplied r2 prompt,
the hardening brief/design/recovery/implementation records, the authority,
request, audit, configuration, deployment, and representative regression-test
paths. The execution fence prohibited child reviewers and all writes except
this report, so this is a single-reviewer adversarial pass rather than a
multi-model consensus result. I did not use credentials, contact a controller,
run deployment code, or modify source.

## Findings

### 1. [warning] The public `readonly` schema description says the opposite of the implemented default

**Location**: `src/mcp_unifi/config.py:320-329`

**Finding**: `Settings.readonly` is implemented with `default=True`, but its
Pydantic field description tells consumers: “Default False so existing
deployments are unaffected.” Pydantic descriptions are part of the public
configuration surface (generated settings/schema/help consumers), so an
operator or downstream integration can be given an incorrect statement about
whether write tools are exposed on first startup.

**Evidence**: The code at line 321 sets `default=True`; the contradictory
sentence is at lines 327-328. The committed `.env.example` also sets
`MCP_UNIFI_READONLY=true`, and the selected design requires read-only by
default. This is therefore stale documentation embedded in the runtime schema,
not an intentional compatibility mode.

**Suggestion**: Change the description to state that the default is `True`
and that writable operation is an explicit opt-in. Add or retain a small
assertion over the exported field description/schema if that public metadata is
relied on by tooling.

## Attention: decision-trail audit

### Attention 1. The initial design-comparison row remains open after a later selection

**Trail rows**: 4 and 7 in `.audit/unifi-hardening.tsv`.

**Evidence**: Row 4 records the three-design comparison with result `open` and
points only to `brief.md`. Row 7 later records the selected design as verified
and points to `selected-design.md`. The later artifact substantially resolves
the decision, but the earlier open row is never closed or cross-referenced.

**Why it matters**: A casual auditor can read the chronological trail as
showing an unresolved design comparison, even though the chosen design is
documented later. This is evidence-trail hygiene, not an implementation
security failure.

**Suggested trail repair**: Mark row 4 as superseded/resolved and link it to
`selected-design.md` (or add a short follow-up row explicitly closing it).

### Attention 2. Verification limits are generally stated accurately

Rows 26, 28, 30, 34, and 35 distinguish synthetic/protocol/artifact/render
checks from unperformed Docker runtime, desktop-install, live-controller, and
physical power-loss verification. The selected transcript excerpts for the
current run likewise record archive inspection and label desktop installation
unverified. I found no overstatement in those entries.

## Review limits

The review examined source and recorded evidence only. It does not prove live
controller compatibility, Kubernetes mount behavior, Docker runtime behavior,
desktop installation, remote publication, or physical power-loss durability.
