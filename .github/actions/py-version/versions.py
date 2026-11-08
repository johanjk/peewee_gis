#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["packaging"]
# ///
"""Parses pyproject.toml requires-python and prints a JSON matrix for CI."""

import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.version import Version


def get_version(entry: dict) -> str | None:
    """Minor version of a stable CPython entry of `uv python list`, else None."""
    if not entry.get("key", "").startswith("cpython"):
        return None
    version_str = entry.get("version")
    if not version_str:
        return None

    v = Version(version_str)
    if v.is_prerelease:
        return None
    return f"{v.major}.{v.minor}"


def get_uv_python_versions() -> list[str]:
    """Get installable CPython minor versions directly from uv."""
    result = subprocess.run(
        ["uv", "python", "list", "--all-versions", "--output-format", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)

    return sorted({d for entry in data if (d := get_version(entry)) is not None}, key=Version)


def parse_args():
    """Command line arguments."""
    parser = argparse.ArgumentParser(
        description="Inspect or process a Python package directory.",
    )
    parser.add_argument(
        "pkg_dir",
        type=Path,
        nargs="?",
        default=Path(),
        help="Path to the package directory (default: .)",
    )
    return parser.parse_args()


def main():
    """Print the CPython minor versions matching requires-python, as JSON."""
    args = parse_args()
    pyproject_path = args.pkg_dir / Path("pyproject.toml")
    if not pyproject_path.exists():
        print("Error: pyproject.toml not found", file=sys.stderr)
        sys.exit(1)

    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)

    requires_python = data.get("project", {}).get("requires-python", ">=3.9")
    spec = SpecifierSet(requires_python)
    compatible = [v for v in get_uv_python_versions() if Version(v) in spec]

    print(json.dumps(compatible))


if __name__ == "__main__":
    main()
