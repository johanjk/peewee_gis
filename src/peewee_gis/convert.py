"""Conversion between shapely and PostGIS values."""

import re
from typing import TYPE_CHECKING, Any, Literal, cast

import peewee as pw
import shapely

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

type Category = Literal["geometry", "geography", "box2d", "box3d", "raster", "other"]
type Box2D = tuple[float, float, float, float]
type Box3D = tuple[float, float, float, float, float, float]

_BOX = re.compile(r"^BOX(?:3D)?\(([^)]*)\)$", re.IGNORECASE)


def load_geometry(value: object) -> shapely.Geometry | None:
    """(E)WKB as hex ``str``, ``bytes`` or ``memoryview`` -> shapely geometry (keeps the SRID)."""
    if value is None:
        return None
    if isinstance(value, shapely.Geometry):
        return value
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (str, bytes)):
        try:
            return shapely.from_wkb(value)
        except NotImplementedError as err:  # shapely has no curve geometries
            msg = f"{err}; convert in SQL, e.g. `.st.CurveToLine()`, or select it with `.raw()`"
            raise NotImplementedError(msg) from err
    msg = f"cannot load a geometry from {type(value).__name__}"
    raise TypeError(msg)


def _box(value: object, n: int) -> tuple[float, ...] | None:
    if value is None:
        return None
    if isinstance(value, tuple) and len(value) == n:
        return tuple(float(x) for x in value)
    m = _BOX.match(str(value).strip())
    if m is None:
        msg = f"not a box: {value!r}"
        raise ValueError(msg)
    nums = tuple(float(x) for corner in m.group(1).split(",") for x in corner.split())
    if len(nums) != n:
        msg = f"expected {n} coordinates in {value!r}"
        raise ValueError(msg)
    return nums


def load_box2d(value: object) -> Box2D | None:
    """``'BOX(xmin ymin,xmax ymax)'`` -> ``(xmin, ymin, xmax, ymax)``."""
    return cast("Box2D | None", _box(value, 4))


def load_box3d(value: object) -> Box3D | None:
    """``'BOX3D(xmin ymin zmin,xmax ymax zmax)'`` -> 6-tuple."""
    return cast("Box3D | None", _box(value, 6))


CONVERTERS: Mapping[str, Callable[[Any], Any]] = {
    "geometry": load_geometry,
    "geography": load_geometry,
    "box2d": load_box2d,
    "box3d": load_box3d,
}


def to_ewkb_hex(geom: shapely.Geometry, srid: int | None = None, output_dimension: int | None = None) -> str:
    """Hex EWKB of ``geom``; ``srid`` is set when the geometry has none (0)."""
    if srid is not None and shapely.get_srid(geom) == 0:
        geom = shapely.set_srid(geom, srid)
    kwargs: dict[str, Any] = {"hex": True, "include_srid": shapely.get_srid(geom) != 0}
    if output_dimension is not None:
        kwargs["output_dimension"] = output_dimension
    return str(shapely.to_wkb(geom, **kwargs))


def literal(geom: shapely.Geometry, sqltype: str = "geometry", srid: int | None = None) -> pw.Cast:
    """``CAST('<hex ewkb>' AS geometry)``: an unambiguous geometry argument."""
    return pw.Cast(pw.Value(to_ewkb_hex(geom, srid), converter=False), sqltype)


def adapt(value: object, srid: int | None = None) -> object:
    """Function argument: shapely geometries become geometry literals.

    ``srid`` is set on geometries without one, e.g. the SRID of the column a chain starts from.
    """
    if isinstance(value, shapely.Geometry):
        return literal(value, srid=srid)
    return value


def context_srid(node: object) -> int | None:
    """SRID of a geometry column (or a cast/alias of one), for SRID-less shapely arguments."""
    while isinstance(node, (pw.Alias, pw.Cast)):
        node = node.node
    srid = getattr(node, "srid", None)
    return srid if isinstance(srid, int) and srid else None
