"""SFCGAL functions on cg, against PostGIS with postgis_sfcgal."""

import peewee as pw
import pytest
import shapely

import peewee_gis as pg


class Footprint(pw.Model):
    height = pw.FloatField()
    geom = pg.GeometryField(pg.GeomType.Polygon, srid=25833)


@pytest.fixture(scope="module")
def setup_database(setup_database):
    setup_database.execute(pg.extension("postgis_sfcgal"))
    yield setup_database


@pytest.fixture(scope="module")
def database_models():
    yield [Footprint]


def test_extrude_volume(postgres):
    Footprint.create(height=10, geom=shapely.box(0, 0, 2, 3))
    solid = Footprint.geom.cg.Extrude(0, 0, Footprint.height).MakeSolid()
    (volume, wkt) = Footprint.select(solid.Volume(), solid.st.AsText()).tuples().get()
    assert volume == pytest.approx(60)
    assert wkt.startswith("POLYHEDRALSURFACE Z")


def test_switch_back_to_st_keeps_conversion(postgres):
    Footprint.create(height=1, geom=shapely.box(0, 0, 1, 1))
    (area,) = Footprint.select(Footprint.geom.st.MakeValid().cg.n3DArea()).tuples().get()
    assert area == pytest.approx(1)
    (skeleton,) = Footprint.select(Footprint.geom.cg.StraightSkeleton()).tuples().get()
    assert skeleton.geom_type == "MultiLineString"  # geometry results convert to shapely on cg too


def test_polyhedral_results_explain_themselves(postgres):
    """GEOS has no TIN/PolyhedralSurface: a clear error, and .st.AsText() as the way out."""
    Footprint.create(height=1, geom=shapely.box(0, 0, 1, 1))
    with pytest.raises(NotImplementedError, match="AsText"):
        Footprint.select(Footprint.geom.cg.Tesselate()).tuples().get()
    (wkt,) = Footprint.select(Footprint.geom.cg.Tesselate().st.AsText()).tuples().get()
    assert wkt.startswith("TIN")
