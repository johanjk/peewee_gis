"""``geometry`` and ``geography`` columns, with shapely as the python type."""

import re
from typing import TYPE_CHECKING, Any, ClassVar, Literal, cast, override

import peewee as pw
import shapely
import shapely.geometry

from .._srid import SRID, as_srid
from ..convert import Category, load_geometry, to_ewkb_hex
from ..operators import SpatialOperators
from ..st.function import Bound, Cast, GeographyCast, GeometryCast, STFunction, make_cast
from .types import Dim, GeomType

if TYPE_CHECKING:
    from ..sqltypes import geography, geometry
    from ..st._generated.api import StBound

    _Field = pw.Field[shapely.Geometry | None]
else:
    _Field = pw.Field

_HEX = re.compile(r"^[0-9A-Fa-f]+$")

type OnSridMismatch = Literal["raise", "transform", "relabel"]
type GeometryInput = shapely.Geometry | str | bytes | memoryview | dict[str, Any] | Any


def to_shapely(value: GeometryInput) -> shapely.Geometry:
    """Accept shapely geometries, WKT, (E)WKB (bytes or hex), GeoJSON dicts and ``__geo_interface__``."""
    if isinstance(value, (shapely.Geometry, bytes, memoryview)):
        return cast("shapely.Geometry", load_geometry(value))
    if isinstance(value, str):
        s = value.strip()
        if _HEX.match(s):
            return cast("shapely.Geometry", load_geometry(s))
        if s.upper().startswith("SRID="):
            srid, _, wkt = s.partition(";")
            return shapely.set_srid(shapely.from_wkt(wkt), int(srid[5:]))
        if s.startswith("{"):
            return shapely.from_geojson(s)
        return shapely.from_wkt(s)
    geo = getattr(value, "__geo_interface__", value)
    if isinstance(geo, dict):
        return shapely.geometry.shape(geo)
    msg = f"cannot convert {type(value).__name__} to a geometry"
    raise TypeError(msg)


class SpatialField(SpatialOperators, _Field):
    """Base of :class:`GeometryField` and :class:`GeographyField`.

    Args:
        geom_type: subtype, e.g. ``GeomType.MultiPolygon`` (``Geometry`` accepts any).
        srid: column SRID, an ``int`` or e.g. a ``pyproj.CRS``; ``0`` for no SRID.
        dim: coordinate dimensions, ``Dim.XYZ`` gives ``PolygonZ``.
        on_srid_mismatch: values carrying another SRID than the column's are rejected
            (``"raise"``), transformed with ``ST_Transform`` (``"transform"``), or
            relabelled (``"relabel"``, the coordinates are kept as they are).
        **kwargs: ``pw.Field`` options (``null``, ``index``, ``column_name``, ...).
    """

    field_type = "GEOMETRY"
    default_index_type = "GIST"
    types: ClassVar[type[GeomType]] = GeomType
    _pg_category: Category = "geometry"

    def __init__(
        self,
        geom_type: GeomType | str = GeomType.Geometry,
        srid: SRID = 4326,
        *,
        dim: Dim = Dim.XY,
        on_srid_mismatch: OnSridMismatch = "raise",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.geom_type: GeomType = GeomType(geom_type)
        self.srid: int = as_srid(srid)
        self.dim: Dim = dim
        self.on_srid_mismatch: OnSridMismatch = on_srid_mismatch

    @override
    def get_modifiers(self) -> list[str | int] | None:  # type: ignore[override]  # ty: ignore[invalid-method-override]
        typmod = f"{self.geom_type.value}{self.dim.value}"
        if self.geom_type is GeomType.Geometry and not self.dim.value and not self.srid:
            return None
        return [typmod, self.srid] if self.srid else [typmod]

    @override
    def python_value(self, value: object) -> shapely.Geometry | None:
        return load_geometry(value)

    @override
    def db_value(self, value: object) -> pw.Node | None:
        if value is None or isinstance(value, pw.Node):
            return value
        try:
            geom = to_shapely(value)
        except NotImplementedError:
            # curves etc. that shapely can't represent: let PostGIS parse WKT/EWKT/hex EWKB
            if not isinstance(value, str):
                raise
            text = value.strip()
            if self.srid and not _HEX.match(text) and not text.upper().startswith("SRID="):
                text = f"SRID={self.srid};{text}"
            return pw.Cast(pw.Value(text, converter=False), self._sql_type)
        srid = shapely.get_srid(geom)
        node: pw.Node
        if srid and self.srid and srid != self.srid:
            if self.on_srid_mismatch == "raise":
                msg = f"{self.name}: geometry has SRID {srid}, the column {self.srid}"
                raise ValueError(msg)
            if self.on_srid_mismatch == "transform":
                lit = pw.Cast(pw.Value(self._ewkb(geom, None), converter=False), "geometry")
                node = STFunction("ST_Transform", (lit, self.srid))
                return pw.Cast(node, self._sql_type) if self._sql_type != "geometry" else node
            geom = shapely.set_srid(geom, self.srid)
        return pw.Cast(pw.Value(self._ewkb(geom, self.srid or None), converter=False), self._sql_type)

    def _ewkb(self, geom: shapely.Geometry, srid: int | None) -> str:
        dims = self.dim.wkb_dimension if self.dim is not Dim.XY else 2
        return to_ewkb_hex(geom, srid, output_dimension=dims)

    @property
    def _sql_type(self) -> str:
        return self.field_type.lower()

    @override
    def cast(self, as_type: str) -> Cast:
        return make_cast(self, as_type)

    def as_geography(self) -> GeographyCast:
        """``CAST(geom AS geography)``: functions on it measure in metres."""
        return GeographyCast(self)

    def as_geometry(self) -> GeometryCast:
        return GeometryCast(self)

    # coordinate shortcuts, numeric results
    @property
    def x(self) -> STFunction:
        """``ST_X(geom)``."""
        return STFunction("ST_X", (self,))

    @property
    def y(self) -> STFunction:
        """``ST_Y(geom)``."""
        return STFunction("ST_Y", (self,))

    @property
    def z(self) -> STFunction:
        """``ST_Z(geom)``."""
        return STFunction("ST_Z", (self,))

    @property
    def m(self) -> STFunction:
        """``ST_M(geom)``."""
        return STFunction("ST_M", (self,))


class GeometryField(SpatialField):
    """PostGIS ``geometry`` column.

    Args:
        geom_type: subtype, e.g. ``GeomType.MultiPolygon`` (``Geometry`` accepts any).
        srid: column SRID, an ``int`` or e.g. a ``pyproj.CRS``; ``0`` for no SRID.
        dim: coordinate dimensions, ``Dim.XYZ`` gives ``PolygonZ``.
        on_srid_mismatch: values carrying another SRID than the column's are rejected
            (``"raise"``), transformed with ``ST_Transform`` (``"transform"``), or
            relabelled (``"relabel"``, the coordinates are kept as they are).
        **kwargs: ``pw.Field`` options (``null``, ``index``, ``column_name``, ...).

    Example:
        ``geom = GeometryField(GeomType.Polygon, srid=4326, index=True)`` creates a
        ``geometry(Polygon, 4326)`` column with a GIST index.
    """

    @property
    def st(self) -> StBound[geometry]:
        """PostGIS functions on this column: ``Model.geom.st.Transform(3857).Area()``."""
        return cast("StBound[geometry]", Bound(self))


class GeographyField(SpatialField):
    """PostGIS ``geography`` column; SRID 4326 by default, measurements in metres."""

    field_type = "GEOGRAPHY"
    _pg_category: Category = "geography"

    @property
    def st(self) -> StBound[geography]:
        """PostGIS functions on this column: ``Model.geog.st.Distance(other)`` is in metres."""
        return cast("StBound[geography]", Bound(self))
