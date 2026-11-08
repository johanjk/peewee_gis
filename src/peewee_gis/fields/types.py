"""Geometry type modifiers: ``geometry(<GeomType><Dim>, <srid>)``."""

from enum import StrEnum


class GeomType(StrEnum):
    """PostGIS geometry subtypes (the typmod of a ``geometry``/``geography`` column)."""

    Geometry = "Geometry"
    Point = "Point"
    LineString = "LineString"
    Polygon = "Polygon"
    MultiPoint = "MultiPoint"
    MultiLineString = "MultiLineString"
    MultiPolygon = "MultiPolygon"
    GeometryCollection = "GeometryCollection"
    CircularString = "CircularString"
    CompoundCurve = "CompoundCurve"
    CurvePolygon = "CurvePolygon"
    MultiCurve = "MultiCurve"
    MultiSurface = "MultiSurface"
    PolyhedralSurface = "PolyhedralSurface"
    Triangle = "Triangle"
    Tin = "Tin"


class Dim(StrEnum):
    """Coordinate dimensions; the value is the typmod suffix (``PointZ``)."""

    XY = ""
    XYZ = "Z"
    XYM = "M"
    XYZM = "ZM"

    @property
    def wkb_dimension(self) -> int:
        """``output_dimension`` for :func:`shapely.to_wkb`."""
        return {"": 2, "Z": 3, "M": 3, "ZM": 4}[self.value]
