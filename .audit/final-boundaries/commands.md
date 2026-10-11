# Final boundary checks

Base source was `f0693d4fb6b31675abea288ef3590b3f538b9fdd` on `harden/final-boundaries`. All checks ran from this isolated worktree with synthetic inputs. No controller or credentials were accessed.

The reproduction command ran before source changes and produced `red.log` with four expected failures and one pass. The queued call made two backend effects instead of one. Three normalized stdout values failed to raise the startup refusal.

```sh
PYTHONPATH=src ../mcp-unifi/.venv/bin/pytest --no-cov tests/test_operator_grants.py tests/test_config.py -k 'queued_intent or stdio_rejects_stdout_audit'
```

The identical command after the source fixes produced `green.log` with five passes.

The following commands produced `focused.log`, `ruff-check.log`, `ruff-format.log`, `mypy.log`, `actionlint.log`, and `diff-check.log` respectively. Empty actionlint and diff logs indicate success. Actionlint and diff checks were also rerun directly and each exited zero.

```sh
PYTHONPATH=src ../mcp-unifi/.venv/bin/pytest --no-cov tests/test_operator_grants.py tests/test_config.py tests/test_audit.py tests/test_audit_integration.py tests/test_write_gate.py tests/test_healthcheck.py tests/test_deployment_security.py
../mcp-unifi/.venv/bin/ruff check src/mcp_unifi/authority.py src/mcp_unifi/modules/_audit.py src/mcp_unifi/server.py tests/test_operator_grants.py tests/test_config.py
../mcp-unifi/.venv/bin/ruff format --check src/mcp_unifi/authority.py src/mcp_unifi/modules/_audit.py src/mcp_unifi/server.py tests/test_operator_grants.py tests/test_config.py
PYTHONPATH=src ../mcp-unifi/.venv/bin/mypy
/private/tmp/unifi-hardening-tools.mNDAIe/actionlint
git diff --check
```

The focused suite passed 139 tests. Ruff lint and formatting passed. Strict mypy passed 66 source files. No full suite or actual MCP transport probe ran in this owner task. The parent owns final full-suite and independent protocol verification.
