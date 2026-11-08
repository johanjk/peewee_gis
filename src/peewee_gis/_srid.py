"""SRID arguments: plain ints, or CRS objects that know their EPSG code."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class SupportsToEpsg(Protocol):
    """E.g. ``pyproj.CRS``."""

    def to_epsg(self) -> int | None: ...


type SRID = int | SupportsToEpsg


def as_srid(value: SRID) -> int:
    """``4326 -> 4326``; ``pyproj.CRS("EPSG:25833") -> 25833``."""
    if isinstance(value, bool):
        msg = f"invalid SRID {value!r}"
        raise TypeError(msg)
    if isinstance(value, int):
        return value
    to_epsg = getattr(value, "to_epsg", None)
    if not callable(to_epsg):
        msg = f"invalid SRID {value!r}, expected an int or an object with .to_epsg()"
        raise TypeError(msg)
    code = to_epsg()
    if not isinstance(code, int):
        msg = f"{value!r} has no EPSG code"
        raise ValueError(msg)  # ruff: ignore[TRY004]
    return code
