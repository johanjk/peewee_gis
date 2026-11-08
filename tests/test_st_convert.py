"""Results of ST_ functions are converted by their SQL type."""

import peewee as pw
import pytest
import shapely

import peewee_gis as pg


class Area(pw.Model):
    geom = pg.GeometryField(pg.GeomType.Polygon, srid=3857)


@pytest.fixture(scope="module")
def database_models():
    yield [Area]


@pytest.fixture
def square(postgres):
    Area.create(geom=shapely.box(0, 0, 100, 100))


def one(*columns):
    return Area.select(*columns).tuples().get()


def test_float(square):
    (area,) = one(Area.geom.st.Area())
    assert area == pytest.approx(10_000)
    assert isinstance(area, float)


def test_bool(square):
    (inside,) = one(Area.geom.st.Intersects(shapely.set_srid(shapely.Point(50, 50), 3857)))
    assert inside is True


def test_text(square):
    (wkt,) = one(Area.geom.st.AsText())
    assert wkt.startswith("POLYGON")


def test_geometry(square):
    (buffered, centroid) = one(Area.geom.st.Buffer(10), Area.geom.st.Centroid().alias("c"))
    assert isinstance(buffered, shapely.Polygon)
    assert centroid.equals(shapely.Point(50, 50))
    assert shapely.get_srid(centroid) == 3857


def test_geometry_from_root(square):
    (p,) = one(pg.st.MakePoint(1, 2).SetSRID(4326))
    assert p.equals(shapely.Point(1, 2))


def test_plain_select_is_not_converted(postgres):
    # peewee only converts results of model queries
    (p,) = pw.Select(columns=[pg.st.MakePoint(1, 2)]).tuples().bind(postgres).get()
    assert isinstance(p, str)
    assert pg.load_geometry(p).equals(shapely.Point(1, 2))


def test_box2d(square):
    (box,) = one(pg.st.Box2D(Area.geom))
    assert box == (0, 0, 100, 100)


def test_raw(square):
    (hexwkb,) = one(Area.geom.st.Centroid().raw())
    assert isinstance(hexwkb, str)


def test_geography_cast_measures_in_metres(postgres):
    line = pg.st.MakeLine(pg.st.MakePoint(10, 60), pg.st.MakePoint(11, 60)).SetSRID(4326)
    (metres, degrees) = (
        pw.Select(columns=[line.as_geography().st.Length(), line.st.Length()]).tuples().bind(postgres).get()
    )
    assert degrees == pytest.approx(1)
    assert metres == pytest.approx(55_800, rel=0.01)  # 1 degree of longitude at 60N


def test_selected_cast_converts(square):
    (g,) = one(Area.geom.st.Transform(4326).as_geography())
    assert isinstance(g, shapely.Polygon)


def test_tile_envelope_named_argument(postgres):
    plain, wide = pg.st.TileEnvelope(3, 4, 2).Area(), pg.st.TileEnvelope(3, 4, 2, margin=0.5).Area()
    (a, b) = pw.Select(columns=[plain, wide]).tuples().bind(postgres).get()
    assert b / a == pytest.approx(4)  # each side grows by 2 * 50%
