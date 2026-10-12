# Journal recovery comment review

Reviewed `cae347a..a01925f5f20ece78a99bc8e188eb124c3f219828` in `network/mcp-unifi-journal-recovery`. The checkout was clean and HEAD matched the target revision. This report is the only file written. The parent owns all source fixes.

## Verdict and counts

No comment deletion or workaround fix is required in this fresh scope. Applied deletions: zero. Proposed deletions: zero. Restored comments: zero. Reruns: zero. New `MUST KILL` flags: zero. No architecture sketch, encoding offer, or unenforced code-comment constraint is needed.

## Keeps and evidence

Keep `src/mcp_unifi/cli/journal.py:1`, the module docstring. `main` passes `__doc__` directly to `argparse.ArgumentParser(description=__doc__)` at line 13. It defines the operator-facing command description. Deleting it changes executable CLI metadata and removes help text. This falls under the public CLI contract exception and the prior acceptance's executable-metadata treatment, not a general exemption for narrative module docstrings. Its claim is supported by the separately registered `mcp-unifi-journal` entry point, the `init` command choice, and `initialize_journal`; it exposes no MCP tool.

Keep the new inline `# noqa: S603` in `tests/test_operator_grants.py:38`. The fixture executes `sys.executable` with fixed module and command arguments. Its only variable argument is a pytest-owned temporary journal pathname passed after `--path`. There is no shell, caller-controlled executable, or arbitrary command argument. The security rule produces a false positive for this fixed test command.

Keep the new inline `# noqa: S603` in `.audit/journal-recovery/reproduce_baseline.py:25`. The reproduction executes the locally resolved Git executable with the literal arguments `show` and `cae347a:src/mcp_unifi/authority.py`. It accepts no input or arbitrary command arguments. PATH and the installed Git executable are the local development trust boundary, as with the prior accepted build commands. This suppression does not excuse model-controlled subprocess input.

Reviewed [Ruff's S603 definition](https://docs.astral.sh/ruff/rules/subprocess-without-shell-equals-true/). The rule detects subprocess calls without a shell and warns about unvalidated arguments; its documentation acknowledges false positives when argument validation cannot be inferred. Both new uses have fixed command structure and trusted local arguments. This is a demonstrated false-positive keep for a security rule, not a style-only classification. No new type, correctness, or safety suppression remains actionable. Existing S603 suppressions in `scripts/build_dxt.py` were unchanged and remain closed under prior acceptance.

## Workarounds and scope

No actual new workaround was found. `Authority.try_record_uncertain_outcome` remains explicitly named best-effort persistence. Its changed failure branch marks the authority unhealthy; it does not conceal a newly accepted recovery bypass. Prior findings about `completion_failed` and the release annotation remain closed and were not reopened.

Inspected the complete changed executable diff, surrounding authority and issuer code, CLI metadata, new baseline reproduction, subprocess initializer, and changed operator documents. Searched the changed Python files for comments, docstrings, suppression markers, and workaround or constraint language. The new journal metadata and two S603 annotations are the complete added comment/docstring/suppression set. No added narration, banner, commented-out code, or thin `IMPORTANT` constraint needs `/how` or `/why` investigation.

Markdown operator instructions, frontmatter descriptions, changelog text, and audit logs are documents or evidence rather than code comments. The new recovery directions describe the supported operator procedure and were not candidates for comment deletion. No new comment appears inside their changed executable examples.

Read `no-comments/SKILL.md`, the Codex platform mapping, the comment-sicko reference, and the prior acceptance and round-two reports. Did not edit application code, inspect credentials, start subprocess services, run runtime tests, create children, or commit. A local Ruff-rule lookup could not run because this checkout has no `.venv/bin/ruff`; the official rule documentation supplied the rule definition instead. Behavior verification remains the parent's work. No open comment-review work remains.
