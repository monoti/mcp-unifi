"""Initialize a new mutation journal outside the MCP protocol."""

from __future__ import annotations

import argparse
from pathlib import Path

from mcp_unifi.authority import initialize_journal
from mcp_unifi.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init"])
    parser.add_argument("--path", type=Path)
    arguments = parser.parse_args()
    try:
        path = arguments.path or Settings().mutation_journal
        if path is None:
            raise ValueError("Configure MCP_UNIFI_MUTATION_JOURNAL or --path.")
        generation = initialize_journal(path.absolute())
    except Exception as exc:
        parser.error(
            f"Journal initialization failed ({type(exc).__name__}). Inspect protected storage."
        )
    print(generation)


if __name__ == "__main__":
    main()
