"""Hatch build hook: render the function catalog into ``src/peewee_gis/st/_generated``.

Only the runtime files (``catalog.py``); the typing (``api.pyi``) is the separate
``peewee_gis-stubs`` package (``stubs/``). Both render from the committed snapshot
``generator/snapshots/postgis-<version>.json`` with ``peewee_gis_generator.build``,
so building needs no network and only jinja2 (``[build-system].requires``).
"""

import sys
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

OUT = Path("src/peewee_gis/st/_generated")


class GenerateHook(BuildHookInterface):  # type: ignore[type-arg]
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:  # ruff: ignore[ARG002]
        if self.target_name != "wheel":  # also covers `version == "editable"`
            return
        root = Path(self.root)
        sys.path.insert(0, str(root / "generator" / "src"))
        try:
            from peewee_gis_generator import build  # ruff: ignore[PLC0415]
            from peewee_gis_generator.render import RUNTIME_FILES  # ruff: ignore[PLC0415]
        finally:
            sys.path.pop(0)
        snapshot = build.snapshot_path()
        if build.render_if_changed(snapshot, root / OUT, RUNTIME_FILES):
            self.app.display_info(f"peewee_gis: rendered {OUT} from {snapshot.name}")
