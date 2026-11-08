"""Tile functions against PostGIS; tiles decoded with mapbox-vector-tile."""

import json

import mapbox_vector_tile
import peewee as pw
import pytest
import shapely

import peewee_gis as pg
from peewee_gis.tiles import TileRegistry, ground_width, martin_config, pixel_size

from .conftest import sql

SCHEMA = "tiles_test"


class Grid(pw.Model):
    ssbid = pw.BigIntegerField()
    year = pw.IntegerField()
    kind = pw.TextField()
    value = pw.FloatField()
    x = pw.IntegerField(default=0)  # a column named like a tile argument
    geom = pg.GeometryField(pg.GeomType.Polygon, srid=4326, index=True)

    class Meta:
        schema = SCHEMA


registry = TileRegistry()


@registry.to_tile_fn(SCHEMA, feature_id="ssbid")
def grid_year(z, x, y, kind: str, year: int = 2024):
    """Grid values per year and kind; 100% made up."""
    return Grid.select(Grid.ssbid, Grid.value, Grid.geom).where(Grid.year == year, Grid.kind == kind)


@registry.to_tile_fn(SCHEMA, feature_id="ssbid", feature_mode="move", layer="cells", simplify=False)
def grid_cells(z, x, y):
    return Grid.select(Grid.ssbid, Grid.x, Grid.geom.st.Transform(25833).alias("g"))


@pytest.fixture(scope="module")
def setup_database(setup_database):
    setup_database.execute_sql(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')
    yield setup_database


@pytest.fixture(scope="module")
def database_models():
    yield [Grid]


@pytest.fixture(scope="module")
def module_database(module_database):
    oslo = shapely.box(10.70, 59.90, 10.80, 59.95)
    bergen = shapely.box(5.30, 60.38, 5.35, 60.40)
    Grid.insert_many(
        [
            {"ssbid": 1, "year": 2024, "kind": "pop", "value": 10.5, "geom": oslo},
            {"ssbid": 2, "year": 2024, "kind": "pop", "value": 3.0, "geom": bergen},
            {"ssbid": 3, "year": 2023, "kind": "pop", "value": 9.0, "geom": oslo},
            {"ssbid": 4, "year": 2024, "kind": "jobs", "value": 1.0, "geom": oslo},
        ],
    ).execute()
    registry.create_all(module_database)
    yield module_database


def decode(tile: bytes) -> dict:
    return mapbox_vector_tile.decode(tile)


# z/x/y tiles containing Oslo
OSLO_Z8 = (8, 135, 74)


def test_function_ddl():
    q, params = sql(grid_year)
    assert params == []
    assert q.startswith(
        'CREATE OR REPLACE FUNCTION "tiles_test"."grid_year"(z integer, x integer, y integer, query_params json) RETURNS bytea LANGUAGE sql STABLE PARALLEL SAFE AS $body$',
    )
    assert '"grid_year".z' in q  # qualified: Grid.x would shadow an unqualified x
    assert "coalesce(CAST(\"grid_year\".query_params ->> 'year' AS integer), 2024)" in q


def test_tile_has_features(module_database):
    tile = decode(grid_year.tile(module_database, *OSLO_Z8, kind="pop"))
    layer = tile["grid_year"]
    assert layer["extent"] == 4096
    (feature,) = layer["features"]
    assert feature["id"] == 1
    assert feature["properties"] == {"ssbid": 1, "value": 10.5}
    assert feature["geometry"]["type"] == "Polygon"


def test_query_params_and_defaults(module_database):
    assert (
        decode(grid_year.tile(module_database, *OSLO_Z8, kind="pop", year=2023))["grid_year"]["features"][0]["id"] == 3
    )
    assert decode(grid_year.tile(module_database, *OSLO_Z8, kind="jobs"))["grid_year"]["features"][0]["id"] == 4


def test_empty_tile_outside_data(module_database):
    assert grid_year.tile(module_database, 8, 0, 0, kind="pop") == b""


def test_feature_mode_move_and_layer_name(module_database):
    tile = decode(grid_cells.tile(module_database, *OSLO_Z8))
    ids = sorted(f["id"] for f in tile["cells"]["features"])
    assert ids == [1, 3, 4]
    assert all("ssbid" not in f["properties"] for f in tile["cells"]["features"])


def test_transformed_geometry_keeps_its_srid():
    q, _ = sql(grid_cells)
    assert "ST_Transform(ST_TileEnvelope(" in q
    assert ", 25833)" in q


def test_standalone_query_matches_function(module_database):
    q = grid_year.query(*OSLO_Z8, kind="pop")
    (standalone,) = module_database.execute(q).fetchone()
    assert bytes(standalone) == grid_year.tile(module_database, *OSLO_Z8, kind="pop")


def test_volatility_and_comment(module_database):
    row = module_database.execute_sql(
        "SELECT p.provolatile, p.proparallel, obj_description(p.oid, 'pg_proc') FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = %s AND p.proname = %s",
        (SCHEMA, "grid_year"),
    ).fetchone()
    provolatile, proparallel, comment = row
    assert (provolatile, proparallel) == ("s", "s")  # STABLE (reads tables), PARALLEL SAFE
    tilejson = json.loads(comment)
    assert tilejson["vector_layers"] == [{"id": "grid_year", "fields": {"ssbid": "Number", "value": "Number"}}]
    assert "100% made up" in tilejson["description"]  # '%' survives the parameterless execute
    assert "kind (text)" in tilejson["description"]
    assert "year (integer, default 2024)" in tilejson["description"]


def test_drop(module_database):
    module_database.execute(grid_cells.drop())
    exists = module_database.execute_sql(
        "SELECT to_regprocedure(%s)",
        (f"{SCHEMA}.grid_cells(integer,integer,integer,json)",),
    )
    assert exists.fetchone()[0] is None


def test_martin_config():
    cfg = martin_config(registry, connection_string="${DATABASE_URL}")
    assert cfg == {
        "postgres": {
            "connection_string": "${DATABASE_URL}",
            "auto_publish": False,
            "functions": {
                "tiles_test.grid_year": {"schema": SCHEMA, "function": "grid_year"},
                "tiles_test.grid_cells": {"schema": SCHEMA, "function": "grid_cells"},
            },
        },
    }


def test_quoted_function_name():
    fn = pg.to_tile_fn('we"ird', name='tile"fn')(grid_cells.fn)
    body = sql(fn)[0]
    assert body.startswith('CREATE OR REPLACE FUNCTION "we""ird"."tile""fn"(')
    assert '"tile""fn".z' in body


def test_validation():
    with pytest.raises(TypeError, match=r"\(z, x, y\)"):
        pg.to_tile_fn("s")(lambda a, b, c: None)

    def no_geom(z, x, y):
        return Grid.select(Grid.ssbid)

    with pytest.raises(ValueError, match="exactly one geometry"):
        sql(pg.to_tile_fn("s")(no_geom))

    def unaliased(z, x, y):
        return Grid.select(Grid.geom.st.Centroid())

    with pytest.raises(TypeError, match="alias"):
        sql(pg.to_tile_fn("s")(unaliased))


def test_scale_helpers():
    assert pixel_size(0, 512) == pytest.approx(78271.517, rel=1e-6)
    assert pixel_size(1) == pytest.approx(pixel_size(0) / 2)
    assert ground_width(0, 60) == pytest.approx(40075016.68 / 2)
