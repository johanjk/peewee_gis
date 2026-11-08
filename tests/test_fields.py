"""Geometry/geography columns against PostGIS."""

import math
import struct

import peewee as pw
import pytest
import shapely

import peewee_gis as pg
from peewee_gis import Dim, GeomType


class Shape(pw.Model):
    poly = pg.GeometryField(GeomType.Polygon, srid=4326, null=True, index=True)
    multi = pg.GeometryField(GeomType.MultiPolygon, srid=25833, null=True)
    point_z = pg.GeometryField(GeomType.Point, srid=4326, dim=Dim.XYZ, null=True)
    any_geom = pg.GeometryField(srid=0, null=True)
    curve = pg.GeometryField(GeomType.CircularString, srid=4326, null=True)
    geog = pg.GeographyField(GeomType.Point, null=True)
    moved = pg.GeometryField(GeomType.Point, srid=25833, on_srid_mismatch="transform", null=True)
    relabel = pg.GeometryField(GeomType.Point, srid=25833, on_srid_mismatch="relabel", null=True)


@pytest.fixture(scope="module")
def database_models():
    yield [Shape]


def roundtrip(**values):
    pk = Shape.insert(**values).execute()
    return Shape.get_by_id(pk)


def test_polygon_roundtrip(postgres):
    box = shapely.box(10, 59, 11, 60)
    row = roundtrip(poly=box)
    assert row.poly.equals(box)
    assert shapely.get_srid(row.poly) == 4326


def test_inputs(postgres):
    box = shapely.box(0, 0, 1, 1)
    for value in (box, box.wkt, shapely.to_wkb(box), shapely.to_wkb(box, hex=True), box.__geo_interface__):
        assert roundtrip(poly=value).poly.equals(box), value
    assert roundtrip(poly=f"SRID=4326;{box.wkt}").poly.equals(box)


def test_z_dimension(postgres):
    row = roundtrip(point_z=shapely.Point(1, 2, 3))
    assert row.point_z.has_z
    assert shapely.get_coordinates(row.point_z, include_z=True).tolist() == [[1, 2, 3]]


def test_untyped_geometry_column(postgres):
    for g in (shapely.Point(1, 1), shapely.LineString([(0, 0), (1, 1)]), shapely.box(0, 0, 1, 1)):
        assert roundtrip(any_geom=g).any_geom.equals(g)


def test_srid_mismatch_raises(postgres):
    point = shapely.set_srid(shapely.Point(10.7, 59.9), 4326)
    with pytest.raises(ValueError, match="SRID 4326"):
        roundtrip(multi=point)


def test_srid_mismatch_transforms(postgres):
    point = shapely.set_srid(shapely.Point(10.7, 59.9), 4326)
    row = roundtrip(moved=point)
    assert shapely.get_srid(row.moved) == 25833
    assert row.moved.x == pytest.approx(261_000, abs=2_000)  # UTM33N easting


def test_srid_mismatch_relabels(postgres):
    point = shapely.set_srid(shapely.Point(1, 2), 4326)
    row = roundtrip(relabel=point)
    assert shapely.get_srid(row.relabel) == 25833
    assert (row.relabel.x, row.relabel.y) == (1, 2)


def test_geography(postgres):
    oslo, bergen = shapely.Point(10.75, 59.91), shapely.Point(5.32, 60.39)
    roundtrip(geog=oslo)
    (dist,) = Shape.select(Shape.geog.st.Distance(bergen)).where(Shape.geog.is_null(False)).tuples().get()
    assert dist == pytest.approx(305_000, rel=0.02)  # metres, not degrees


def test_curve(postgres):
    Shape.insert(curve="CIRCULARSTRING(0 0, 1 1, 2 0)").execute()
    q = Shape.select(Shape.curve.st.Length(), Shape.curve.st.CurveToLine()).where(Shape.curve.is_null(False))
    length, line = q.tuples().get()
    assert length == pytest.approx(math.pi, rel=1e-3)
    assert isinstance(line, shapely.LineString)
    # shapely has no curve types: a clear error, not garbage
    with pytest.raises(NotImplementedError, match="CurveToLine"):
        Shape.select(Shape.curve).where(Shape.curve.is_null(False)).tuples().get()


def test_srid_less_arguments_get_the_column_srid(postgres):
    roundtrip(poly=shapely.box(0, 0, 10, 10))
    assert Shape.select().where(Shape.poly.st.Contains(shapely.Point(5, 5))).count() == 1


def test_filter_by_geometry(postgres):
    roundtrip(poly=shapely.box(0, 0, 10, 10))
    roundtrip(poly=shapely.box(20, 20, 30, 30))
    inside = shapely.Point(5, 5)
    assert Shape.select().where(Shape.poly.st.Contains(inside)).count() == 1
    assert Shape.select().where(Shape.poly.bbox_overlaps(shapely.box(4, 4, 25, 25))).count() == 2
    nearest = Shape.select().where(Shape.poly.is_null(False)).order_by(Shape.poly.knn(shapely.Point(19, 19))).first()
    assert nearest.poly.bounds == (20, 20, 30, 30)


def test_gist_index_exists(postgres):
    (indexdef,) = (
        pw
        .Select(columns=[pw.SQL("indexdef")])
        .from_(pw.SQL("pg_indexes"))
        .where(pw.SQL("indexname = 'shape_poly'"))
        .tuples()
        .bind(postgres)
        .get()
    )
    assert "USING gist" in indexdef


def test_to_shapely_explains_curves():
    """Field input shares load_geometry's message for geometries shapely can't hold."""
    circular_string = struct.pack("<BII6d", 1, 8, 3, 0, 0, 1, 1, 2, 0)  # WKB type 8
    with pytest.raises(NotImplementedError, match="CurveToLine"):
        pg.to_shapely(circular_string)
