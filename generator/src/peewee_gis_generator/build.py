"""Rendering from hatch build hooks (peewee_gis and peewee_gis-stubs).

Kept free of third-party imports except jinja2 (via :mod:`.render`): it runs in the
isolated build environment of the packages, which only has hatchling, hatch-vcs and jinja2.
"""

import hashlib
from pathlib import Path

GENERATOR_SRC = Path(__file__).parents[1]
SNAPSHOTS = GENERATOR_SRC.parent / "snapshots"

POSTGIS_VERSION = "3.6"
"""PostGIS version both packages render from (``snapshots/postgis-<version>.json``); the only place to bump."""


def snapshot_path(postgis_version: str = POSTGIS_VERSION, snapshots: Path = SNAPSHOTS) -> Path:
    path = snapshots / f"postgis-{postgis_version}.json"
    if not path.is_file():
        msg = f"missing {path}; run `peewee-gis-generator scrape {postgis_version}`"
        raise FileNotFoundError(msg)
    return path


def digest(snapshot: Path, files: tuple[str, ...]) -> str:
    """Hash of everything the output depends on: snapshot, generator sources, selected files."""
    h = hashlib.sha256(snapshot.read_bytes())
    h.update(",".join(files).encode())
    for p in sorted(GENERATOR_SRC.rglob("*")):
        if p.suffix in {".py", ".jinja"} and "__pycache__" not in p.parts:
            h.update(p.relative_to(GENERATOR_SRC).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def render_if_changed(snapshot: Path, output_dir: Path, files: tuple[str, ...]) -> bool:
    """Render ``files`` into ``output_dir`` unless a ``.stamp`` says they are current."""
    from .render import render_snapshot  # ruff: ignore[PLC0415] - jinja2 only when rendering

    stamp = output_dir / ".stamp"
    key = digest(snapshot, files)
    if stamp.is_file() and stamp.read_text() == key and all((output_dir / f).is_file() for f in files):
        return False
    render_snapshot(snapshot, output_dir, files=files)
    stamp.write_text(key)
    return True
