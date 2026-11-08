"""Data model shared by the scraper and the renderer.

The scraper turns the PostGIS manual into a :class:`Snapshot`, which is stored as
JSON (``snapshots/postgis-<version>.json``). The renderer only reads snapshots, so
building the runtime package needs neither network access nor an HTML parser.
"""

import json
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

SNAPSHOT_FORMAT = 1


@dataclass(frozen=True, slots=True)
class Argument:
    """Single function argument as written in the manual."""

    name: str
    type_: str
    """Normalised PostgreSQL type, e.g. ``geometry``, ``double precision``, ``geometry[]``."""
    default: str | None = None
    variadic: bool = False


@dataclass(frozen=True, slots=True)
class Signature:
    """One overload of a function."""

    args: list[Argument]
    ret: str


@dataclass(frozen=True, slots=True)
class SeeAlso:
    """Related function reference."""

    title: str
    url: str


@dataclass(frozen=True, slots=True)
class Example:
    """Single SQL code example."""

    desc: str | None
    code: str | None


@dataclass(frozen=True, slots=True)
class Function:
    """Parsed function page."""

    name: str
    """SQL name, e.g. ``ST_3DArea``."""
    url: str
    summary: str | None
    description: str | None
    signatures: list[Signature]
    see_also: list[SeeAlso] = field(default_factory=list[SeeAlso])
    examples: list[Example] = field(default_factory=list[Example])
    other_urls: list[str] = field(default_factory=list[str])
    """Further pages documenting overloads of the same name (e.g. the raster variant)."""


@dataclass(frozen=True, slots=True)
class Snapshot:
    """All functions scraped from one PostGIS manual version."""

    postgis_version: str
    functions: list[Function]
    format: int = SNAPSHOT_FORMAT

    def dump(self, path: Path) -> None:
        data = asdict(self)
        path.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Snapshot:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("format") != SNAPSHOT_FORMAT:
            msg = f"{path}: unsupported snapshot format {data.get('format')!r}, expected {SNAPSHOT_FORMAT}"
            raise ValueError(msg)
        return cls(
            postgis_version=data["postgis_version"],
            functions=[_function(f) for f in data["functions"]],
        )


def _function(d: dict[str, Any]) -> Function:
    return Function(
        name=d["name"],
        url=d["url"],
        summary=d["summary"],
        description=d["description"],
        signatures=[Signature(args=[Argument(**a) for a in s["args"]], ret=s["ret"]) for s in d["signatures"]],
        see_also=[SeeAlso(**x) for x in d["see_also"]],
        examples=[Example(**x) for x in d["examples"]],
        other_urls=d.get("other_urls", []),
    )
