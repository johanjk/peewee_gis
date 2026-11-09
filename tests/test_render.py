"""SQL rendering; no database needed."""

import peewee as pw
import pytest
import shapely

import peewee_gis as pg
from peewee_gis.st._generated import catalog

from .conftest import COMPILER, sql


class Poly(pw.Model):
    geom = pg.GeometryField(pg.GeomType.Polygon, srid=4326, index=True)
    geog = pg.GeographyField(pg.GeomType.Point)
    big = pg.GeometryField(pg.GeomType.MultiPolygon, srid=25833, dim=pg.Dim.XYZ, null=True)
    anything = pg.GeometryField(srid=0, null=True)

    class Meta:
        database = COMPILER


def test_chain_puts_previous_value_first():
    q, params = sql(Poly.geom.st.Transform(3857).Simplify(10))
    assert q == 'ST_Simplify(ST_Transform("t1"."geom", %s), %s)'
    assert params == [3857, 10]


def test_root_and_bound_render_the_same():
    assert sql(pg.st.Transform(Poly.geom, 3857)) == sql(Poly.geom.st.Transform(3857))
    assert sql(pg.st.on(Poly.geom).Area()) == sql(Poly.geom.st.Area())
    assert sql(pg.st[Poly.geom].Area()) == sql(Poly.geom.st.Area())


def test_names_from_catalog():
    assert sql(pg.st.n3DDistance(Poly.geom, Poly.geom))[0] == 'ST_3DDistance("t1"."geom", "t1"."geom")'
    assert sql(pg.st.Box2D(Poly.geom))[0] == 'Box2D("t1"."geom")'
    assert sql(pg.st.postgis_srs_codes("EPSG"))[0] == "postgis_srs_codes(%s)"
    assert catalog.NAMES["AsMVTGeom"] == "ST_AsMVTGeom"


def test_unknown_names_fall_back_to_st_prefix():
    assert sql(pg.st.SomethingNew(1))[0] == "ST_SomethingNew(%s)"
    assert sql(pg.st.n4DThing(1))[0] == "ST_4DThing(%s)"


def test_private_and_dunder_attributes_are_not_functions():
    with pytest.raises(AttributeError):
        _ = pg.st._private
    with pytest.raises(AttributeError):
        _ = Poly.geom.st.Area().__deepcopy_not_there__


def test_named_arguments():
    q, params = sql(pg.st.TileEnvelope(3, 4, 2, margin=64 / 4096))
    assert q == "ST_TileEnvelope(%s, %s, %s, margin => %s)"
    assert params == [3, 4, 2, 64 / 4096]
    # python keywords: trailing underscore is dropped
    assert sql(pg.st.Foo(1, from_=2))[0] == "ST_Foo(%s, from => %s)"


def test_schema_qualified():
    st = pg.st.in_schema("extensions")
    assert sql(st.Area(Poly.geom))[0] == '"extensions".ST_Area("t1"."geom")'
    assert sql(st.Area(Poly.geom).Buffer(1))[0] == '"extensions".ST_Buffer("extensions".ST_Area("t1"."geom"), %s)'


def test_identifiers_are_quoted_or_rejected():
    assert sql(pg.st.in_schema('we"ird').Area(Poly.geom))[0] == '"we""ird".ST_Area("t1"."geom")'
    with pytest.raises(ValueError, match="invalid function name"):
        getattr(pg.st, "X(1); DROP TABLE t; --")(Poly.geom)
    with pytest.raises(ValueError, match="invalid argument name"):
        pg.NamedArgument("a => 1, b", 2)


def test_shapely_arguments_become_geometry_literals():
    q, params = sql(Poly.geom.st.Intersects(shapely.Point(1, 2)))
    assert q == 'ST_Intersects("t1"."geom", CAST(%s AS geometry))'
    assert shapely.from_wkb(params[0]).equals(shapely.Point(1, 2))


def test_cast_keeps_the_cast_when_chained():
    q, _ = sql(Poly.geom.as_geography().st.Length())
    assert q == 'ST_Length(CAST("t1"."geom" AS geography))'
    q, _ = sql(Poly.geom.cast("geography").st.Length())
    assert q == 'ST_Length(CAST("t1"."geom" AS geography))'
    q, _ = sql(pg.st.MakeLine(Poly.geom, Poly.geom).as_geography().st.Length())
    assert q == 'ST_Length(CAST(ST_MakeLine("t1"."geom", "t1"."geom") AS geography))'


def test_result_conversion_follows_sql_type():
    assert Poly.geom.st.Transform(3857)._python_value is pg.load_geometry
    assert Poly.geom.st.Area()._coerce is False  # never the field's converter on a float
    assert pg.st.Box2D(Poly.geom)._python_value is pg.load_box2d
    assert Poly.geom.st.Transform(3857).raw()._coerce is False


def test_result_conversion_dispatches_on_first_argument():
    # ST_Envelope(geometry) -> geometry, ST_Envelope(raster) -> geometry; ST_Union: raster -> raster
    assert pg.st.Union(Poly.geom)._pg_category == "geometry"
    assert pg.st.Union(Poly.geog.as_geometry())._pg_category == "geometry"
    assert pg.st.Union(pw.SQL("rast"))._pg_category == "other"  # unknown first argument: ambiguous


def test_operators():
    p = shapely.Point(0, 0)
    assert sql(Poly.geom.bbox_overlaps(Poly.geom))[0] == '("t1"."geom" && "t1"."geom")'
    assert sql(Poly.geom.bbox_overlaps(Poly.geom, nd=True))[0] == '("t1"."geom" &&& "t1"."geom")'
    assert sql(Poly.geom.same_bbox(p))[0] == '("t1"."geom" ~= CAST(%s AS geometry))'
    assert sql(Poly.geom.knn(p))[0] == '("t1"."geom" <-> CAST(%s AS geometry))'
    assert sql(Poly.geom.st.Centroid().bbox_within(Poly.geom))[0] == '(ST_Centroid("t1"."geom") @ "t1"."geom")'
    # peewee's own operators are untouched
    assert sql(Poly.geom == p)[0] == '("t1"."geom" = CAST(%s AS geometry))'


def test_ddl():
    q, _ = Poly._schema._create_table().query()
    assert '"geom" GEOMETRY(Polygon, 4326) NOT NULL' in q
    assert '"geog" GEOGRAPHY(Point, 4326) NOT NULL' in q
    assert '"big" GEOMETRY(MultiPolygonZ, 25833)' in q
    assert '"anything" GEOMETRY,' in q or q.endswith('"anything" GEOMETRY)')
    indexes = [i.query()[0] for i in Poly._schema._create_indexes()]
    assert 'CREATE INDEX IF NOT EXISTS "poly_geom" ON "poly" USING GIST ("geom")' in indexes


def test_extension():
    assert sql(pg.extension())[0] == 'CREATE EXTENSION IF NOT EXISTS "postgis"'
    assert sql(pg.extension("btree_gist", schema="ext", cascade=True))[0] == (
        'CREATE EXTENSION IF NOT EXISTS "btree_gist" SCHEMA "ext" CASCADE'
    )


class FakeCRS:
    code = 25833

    def to_epsg(self):
        return self.code


def test_srid_accepts_crs_objects():
    assert pg.GeometryField(srid=FakeCRS()).srid == 25833
    with pytest.raises(TypeError):
        pg.GeometryField(srid="4326")
