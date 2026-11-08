"""Check the wheels: the catalog in peewee_gis, the typing in peewee_gis-stubs only."""

import sys
import zipfile
from pathlib import Path

RULES = {
    "peewee_gis-": {
        "required": [
            "peewee_gis/py.typed",
            "peewee_gis/st/_generated/__init__.py",
            "peewee_gis/st/_generated/catalog.py",
        ],
        "forbidden": ["peewee_gis/st/_generated/api.pyi"],
    },
    "peewee_gis_stubs-": {
        "required": ["peewee_gis-stubs/py.typed", "peewee_gis-stubs/st/_generated/api.pyi"],
        "forbidden": [],
    },
}


def main() -> None:
    found = 0
    for prefix, rule in RULES.items():
        for wheel in sorted(Path("dist").glob(f"{prefix}[0-9]*.whl")):
            found += 1
            with zipfile.ZipFile(wheel) as z:
                names = set(z.namelist())
                missing = [r for r in rule["required"] if r not in names]
                extra = [f for f in rule["forbidden"] if f in names]
                if missing or extra:
                    sys.exit(f"{wheel.name}: missing {missing}, must not contain {extra}")
                if prefix.startswith("peewee_gis_stubs") and z.read("peewee_gis-stubs/py.typed").strip() != b"partial":
                    sys.exit(f"{wheel.name}: py.typed must say 'partial'")
            print(f"{wheel.name}: ok ({len(names)} files)")  # ruff: ignore[T201]
    if found < len(RULES):
        sys.exit("expected a peewee_gis and a peewee_gis-stubs wheel in dist/")


if __name__ == "__main__":
    main()
