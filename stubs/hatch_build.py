"""Hatch build hook: render ``api.pyi`` (typing and docstrings) from the committed snapshot.

The generator is ``../generator`` in the repository, or ``generator/`` inside the sdist.
"""

import sys
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

OUT = Path("peewee_gis-stubs/st/_generated")


class GenerateHook(BuildHookInterface):  # type: ignore[type-arg]
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:  # ruff: ignore[ARG002]
        if self.target_name != "wheel":  # also covers `version == "editable"`
            return
        root = Path(self.root)
        generator = next(p for p in (root / "generator", root.parent / "generator") if (p / "src").is_dir())
        sys.path.insert(0, str(generator / "src"))
        try:
            from peewee_gis_generator import build  # ruff: ignore[PLC0415]
            from peewee_gis_generator.render import STUB_FILES  # ruff: ignore[PLC0415]
        finally:
            sys.path.pop(0)
        snapshot = build.snapshot_path(snapshots=generator / "snapshots")
        if build.render_if_changed(snapshot, root / OUT, STUB_FILES):
            self.app.display_info(f"peewee_gis-stubs: rendered {OUT} from {snapshot.name}")
