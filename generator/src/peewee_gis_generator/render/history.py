"""Functions of older PostGIS versions that the current one no longer has.

A function dropped from the manual stays in the typing, marked ``@deprecated`` with what
the manuals say about it ("Not in the PostGIS 3.8 manual (last documented in 3.7).
Deprecated since 3.5.0: use CG_3DArea instead."), so users upgrading PostGIS get a warning
naming the replacement instead of an unknown attribute.

The manual is the only source: a function missing from it may still be installed (PostGIS
keeps deprecated functions for a while), so the message says what the manual shows and no
more.
"""

import re
from dataclasses import replace
from typing import TYPE_CHECKING

from . import typemap

if TYPE_CHECKING:
    from pathlib import Path

    from ..model import Function, Snapshot

_SNAPSHOT_NAME = re.compile(r"^postgis-(?P<version>\d+(?:\.\d+)+)\.json$")
_NOTICE = re.compile(r"^Deprecated(?: since PostGIS (?P<since>\d+(?:\.\d+)*))?\.\s*(?P<rest>.*)$")


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in version.split("."))


def older_snapshots(snapshot: Path) -> list[Path]:
    """``postgis-<version>.json`` files next to ``snapshot`` for older versions, oldest first."""
    m = _SNAPSHOT_NAME.match(snapshot.name)
    if m is None:
        return []
    current = version_key(m["version"])
    found = [
        (version_key(o["version"]), p)
        for p in snapshot.parent.glob("postgis-*.json")
        if (o := _SNAPSHOT_NAME.match(p.name)) is not None and version_key(o["version"]) < current
    ]
    return [p for _, p in sorted(found)]


def _lower_first(text: str) -> str:
    """``Use X instead`` -> ``use X instead``; a leading name (``ST_Foo is ...``) is kept."""
    word = text.split(" ", 1)[0]
    return text[0].lower() + text[1:] if word[1:].islower() else text


def notice(f: Function, last: str, current: str, current_name: str | None, *, renamed_in: str | None = None) -> str:
    """Deprecation message for ``f``, documented up to PostGIS ``last`` but not in ``current``.

    ``current_name``: the current spelling, when only the case changed (SQL names are
    case-insensitive, so the old attribute still works), first documented in ``renamed_in``
    (default: ``current``).
    """
    if current_name is not None:
        return f"Spelled {current_name} since PostGIS {renamed_in or current}: use st.{typemap.py_name(current_name)}."
    text = f"Not in the PostGIS {current} manual (last documented in {last})."
    if f.deprecated and (m := _NOTICE.match(f.deprecated)):
        since, rest = m["since"], m["rest"].strip()
        text += f" Deprecated since {since}" if since else " Deprecated"
        text += f": {_lower_first(rest)}" if rest else "."
    return text


def removed(current: Snapshot, history: list[Snapshot]) -> list[Function]:
    """Functions documented in ``history`` but not in ``current``, each from the newest snapshot that has it."""
    names = {f.name for f in current.functions}
    # rendered names only: a type page (box2d) has no signatures and no attribute
    by_lower = {f.name.lower(): f.name for f in current.functions if f.signatures}
    ordered = sorted(history, key=lambda s: version_key(s.postgis_version))
    spelled = [{f.name for f in s.functions} for s in ordered]

    def since(name: str, after: int) -> str:
        """First version after snapshot ``after`` that spells ``name`` exactly so."""
        later = (ordered[j].postgis_version for j in range(after + 1, len(ordered)) if name in spelled[j])
        return next(later, current.postgis_version)

    last: dict[str, tuple[Function, int]] = {}
    for i, snap in enumerate(ordered):
        for f in snap.functions:
            if f.name not in names:
                last[f.name] = (f, i)  # newer snapshots overwrite older ones
    out = [
        replace(
            f,
            deprecated=notice(
                f,
                ordered[i].postgis_version,
                current.postgis_version,
                name,
                renamed_in=since(name, i) if name else None,
            ),
        )
        for f, i in last.values()
        for name in [by_lower.get(f.name.lower())]
    ]
    return sorted(out, key=lambda f: f.name.lower())
