"""Build and verify a host-platform DXT directory from hashed dependencies."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(destination: Path) -> None:
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("Choose a new output directory to avoid retaining stale dependencies.")
    bundle = destination / "bundle"
    bundle.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="mcp-unifi-build-") as temporary:
        environment = Path(temporary) / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)  # noqa: S603
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        project = Path(temporary) / "project"
        commands = [
            ["install", "--require-hashes", "-r", str(ROOT / "requirements-build.lock")],
            [
                "install",
                "--require-hashes",
                "--target",
                str(bundle),
                "-r",
                str(ROOT / "requirements.lock"),
            ],
            ["install", "--no-deps", "--no-build-isolation", "--target", str(project), str(ROOT)],
        ]
        for command in commands:
            subprocess.run([str(python), "-m", "pip", *command], check=True)  # noqa: S603
        shutil.copytree(project, bundle, dirs_exist_ok=True)
        manifest = json.loads((ROOT / "manifest.json").read_text())
        manifest["compatibility"]["platforms"] = [sys.platform]
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        probe = (
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from importlib.metadata import version; "
            "from importlib.metadata import distribution; "
            "import mcp_unifi.server; "
            "assert version('mcp-unifi') == sys.argv[2]; "
            "assert mcp_unifi.server.__file__.startswith(sys.argv[1]); "
            "names = {item.name for item in distribution('mcp-unifi').entry_points}; "
            "assert {'mcp-unifi', 'mcp-unifi-approve', 'mcp-unifi-journal'} <= names; "
            "print('Verified DXT import and version ' + sys.argv[2])"
        )
        subprocess.run(  # noqa: S603
            [str(python), "-I", "-c", probe, str(bundle), manifest["version"]],
            check=True,
            cwd=temporary,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    build(parser.parse_args().destination)


if __name__ == "__main__":
    main()
