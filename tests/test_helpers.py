import json

import peewee as pw
import pytest
import shapely

import peewee_gis as pg
from peewee_gis.helpers import CreateMaterializedView, cluster, subdivided_view

from .conftest import sql


class Region(pw.Model):
    code = pw.IntegerField()
    scale = pw.IntegerField(null=True)
    name = pw.TextField(null=True)
    geom = pg.GeometryField(pg.GeomType.MultiPolygon, srid=4326, null=True)


@pytest.fixture(scope="module")
def setup_database(setup_database):
    setup_database.execute(pg.extension("btree_gist"))
    yield setup_database


@pytest.fixture(scope="module")
def database_models():
    yield [Region]


def test_clean_renders():
    q, params = sql(pg.clean(Region.geom, grid_size=1e-5))
    assert q == 'ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_ReducePrecision(ST_MakeValid("t1"."geom"), %s)), %s))'
    assert params == [1e-5, 3]


def test_clean_fixes_bowtie(postgres):
    bowtie = shapely.from_wkt("POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))")
    assert not bowtie.is_valid
    Region.create(code=0)
    (fixed,) = Region.select(pg.clean(bowtie).alias("g")).tuples().get()
    assert fixed.is_valid
    assert fixed.geom_type == "MultiPolygon"


def test_gist_index(postgres):
    idx = pg.gist_index(Region, Region.geom, Region.scale)
    assert sql(idx)[0] == 'CREATE INDEX IF NOT EXISTS "region_geom_scale" ON "region" USING GIST ("geom", "scale")'
    postgres.execute(idx)
    postgres.execute(cluster(Region, idx))
    with pytest.raises(ValueError, match="geometry"):
        pg.gist_index(Region, Region.scale)


def test_copy_geometries(postgres):
    rows = [
        {"code": 1, "name": "tab\tand\\slash", "geom": shapely.MultiPolygon([shapely.box(0, 0, 1, 1)])},
        (2, "none", None),
    ]
    assert pg.copy_geometries(Region, rows, [Region.code, Region.name, Region.geom]) == 2
    one = Region.get(Region.code == 1)
    assert one.name == "tab\tand\\slash"
    assert one.geom.equals(shapely.MultiPolygon([shapely.box(0, 0, 1, 1)]))
    assert Region.get(Region.code == 2).geom is None


def test_copy_geometries_transforms(postgres):
    utm = shapely.MultiPolygon([shapely.box(261_000, 6_643_000, 262_000, 6_644_000)])
    pg.copy_geometries(Region, [(3, utm)], [Region.code, Region.geom], src_srid=25833)
    pg.copy_geometries(Region, [(4, utm)], [Region.code, Region.geom], src_srid=25833)  # staging table reused
    geom = Region.get(Region.code == 3).geom
    assert shapely.get_srid(geom) == 4326
    assert 10.6 < geom.centroid.x < 10.8


def test_feature_collection(postgres):
    Region.create(code=7, name="a", geom=shapely.MultiPolygon([shapely.box(0, 0, 1, 1)]))
    q = pg.feature_collection(
        Region.select(Region.code, Region.name, Region.geom).where(Region.code == 7),
        id_column="code",
    )
    (fc,) = postgres.execute(q).fetchone()
    fc = fc if isinstance(fc, dict) else json.loads(fc)
    (feature,) = fc["features"]
    assert fc["type"] == "FeatureCollection"
    assert feature["id"] == 7
    assert feature["properties"] == {"name": "a"}
    assert shapely.geometry.shape(feature["geometry"]).equals(shapely.MultiPolygon([shapely.box(0, 0, 1, 1)]))


def test_feature_collection_empty(postgres):
    (fc,) = postgres.execute(
        pg.feature_collection(Region.select(Region.code, Region.geom).where(Region.code == -1)),
    ).fetchone()
    assert (fc if isinstance(fc, dict) else json.loads(fc))["features"] == []


def test_subdivided_view(postgres):
    big = shapely.MultiPolygon([shapely.Point(10, 60).buffer(1, quad_segs=256)])
    Region.create(code=9, geom=big)
    view = subdivided_view(
        "region_parts",
        Region.select(Region.code, Region.geom).where(Region.code == 9),
        Region.geom,
        max_vertices=32,
    )
    postgres.execute(view)
    (n,) = postgres.execute_sql("SELECT count(*) FROM region_parts").fetchone()
    assert n > 4
    postgres.execute(view.refresh())
    postgres.execute(view.drop())


def test_copy_geometries_never_drops_a_permanent_table(postgres):
    """The staging table lives in pg_temp; a real table with its name is left alone."""
    postgres.execute_sql('CREATE TABLE "_pg_copy_region" (keep integer)')
    postgres.execute_sql('INSERT INTO "_pg_copy_region" VALUES (1)')
    utm = shapely.MultiPolygon([shapely.box(600000, 6640000, 601000, 6641000)])
    pg.copy_geometries(Region, [(5, utm)], [Region.code, Region.geom], src_srid=25833)
    # unqualified on purpose: the staging table must not shadow it either
    assert postgres.execute_sql('SELECT keep FROM "_pg_copy_region"').fetchall() == [(1,)]
    assert Region.select().where(Region.code == 5).count() == 1


def test_materialized_view_with_percent_literal(postgres):
    """Inlined values are escaped for psycopg's empty parameter list."""
    Region.create(code=11, name="a%b")
    view = CreateMaterializedView("region_pct", Region.select(Region.code).where(Region.name ** "a%"))
    postgres.execute(view)
    assert postgres.execute_sql("SELECT code FROM region_pct").fetchall() == [(11,)]
    postgres.execute(view.drop())
