# Functions

```python
import peewee as pw
import shapely

import peewee_gis as pg

db = pw.PostgresqlDatabase(None)


class Area(pw.Model):
    name = pw.TextField()
    geom = pg.GeometryField(pg.GeomType.MultiPolygon, srid=4326)

    class Meta:
        database = db


def sql(node):
    return db.get_sql_context().sql(node).query()
```

## `st` and chaining

`pg.st` has every PostGIS function, without the `ST_` prefix. A field's `.st` (and every
function result) chains: the previous value becomes the first argument.

```python
assert sql(pg.st.Transform(Area.geom, 3857)) == sql(Area.geom.st.Transform(3857))
assert sql(Area.geom.st.Transform(3857).Area())[0] == 'ST_Area(ST_Transform("t1"."geom", %s))'
```

Names that start with a digit get an `n`: `st.n3DDistance` is `ST_3DDistance`. Functions without
the prefix keep their name: `st.Box2D`, `st.postgis_srs_codes`, `st.CG_3DArea` (SFCGAL).
Topology and tiger geocoder functions are not included; they live in their own schemas
(use `pw.fn`).

`st.on(node)` chains on anything, e.g. a column of a subquery:

```python
sub = Area.select(Area.geom.st.Centroid().alias("c")).alias("sub")
assert sql(pg.st.on(sub.c.c).X())[0] == 'ST_X("sub"."c")'
```

Optional arguments can be passed by name (PostgreSQL's `name => value`):

```python
assert sql(pg.st.TileEnvelope(3, 4, 2, margin=0.125))[0] == "ST_TileEnvelope(%s, %s, %s, margin => %s)"
```

Shapely geometries passed as arguments become `CAST('<ewkb>' AS geometry)`. Without an SRID
they get the SRID of the column the chain starts from:

```python
q, params = sql(Area.geom.st.Contains(shapely.Point(10.7, 59.9)))
assert q == 'ST_Contains("t1"."geom", CAST(%s AS geometry))'
assert shapely.get_srid(shapely.from_wkb(params[0])) == 4326
```

PostGIS installed outside the search path: `pg.st.in_schema("extensions")`.

## Typing

With `peewee_gis-stubs` installed (`pip install "peewee_gis[typing]"`, see
[the README](../README.md#typing)), each call is typed by the SQL type of the chained value,
and shows the manual's description:

```py
Area.geom.st  # StBound[geometry]
Area.geom.st.Transform(3857)  # StChain[geometry]
Area.geom.st.Area()  # StChain[float]
Area.geom.st.Area().Transform(1)  # error: Transform needs a geometry
Area.geom.st.Area(True)  # error: use_spheroid is geography-only
Area.geom.as_geography().st.Area(True)  # ok
```

Functions the manual deprecates are marked `@deprecated` (PEP 702), with the manual's
replacement as message: editors strike them through, and type checkers report them when
their deprecation check is on (pyright `reportDeprecated`, mypy `--enable-error-code
deprecated`; ty warns by default).

Functions that were documented in an older PostGIS manual (back to 3.2, the oldest
supported version) but no longer are, stay available and typed, deprecated with what the
manuals say: the last version documenting them and, if there was one, the deprecation
notice naming the replacement. Upgrading PostGIS then shows a warning with the way forward
instead of an unknown attribute.

```py
pg.st.MapAlgebraExpr(rast, "8BUI", "[rast] * 2")  # deprecated: use ST_MapAlgebra (expression version)
Area.geom.st.n3DArea()  # deprecated since 3.5.0: use CG_3DArea
Area.geom.st.Zmflag()  # spelled ST_ZMFlag since PostGIS 3.7: use st.ZMFlag
```

A function missing from the manual may still be installed: PostGIS keeps deprecated
functions for a while, so the message only says what the manual shows.

`StChain`, `StBound` and the SQL type markers (`peewee_gis.sqltypes.geometry`, ...) can be
used in annotations; they exist at runtime with or without the stubs. Without the stubs,
these calls are untyped (`Any`).

## Casts

`.as_geography()` / `.as_geometry()` (or `.cast("geography")`) keep the cast when chaining:
geography functions measure in metres.

```python
assert sql(Area.geom.as_geography().st.Area())[0] == 'ST_Area(CAST("t1"."geom" AS geography))'
```

## Result conversion

The catalog knows each function's result type (per type of its first argument):

* `geometry`/`geography` results are shapely geometries, with their SRID;
* `box2d`/`box3d` are tuples `(xmin, ymin, xmax, ymax)`;
* everything else is left to the driver (`float`, `bool`, `str`, `bytes`, ...).

`.raw()` turns the conversion off. peewee only converts results of model queries
(`Model.select(...)`); a bare `pw.Select` returns the driver's values, which
`pg.load_geometry` converts.

Curves (CircularString, ...) can't be represented in shapely; select them with
`.st.CurveToLine()`, or `.raw()`.

## Operators

Bounding box operators are methods; `==` stays SQL `=`.

| method | operator |
|---|---|
| `bbox_overlaps(x)`, `bbox_overlaps(x, nd=True)` | `&&`, `&&&` |
| `bbox_contains(x)` / `bbox_within(x)` | `~` / `@` |
| `same_bbox(x)` | `~=` |
| `left_of`, `right_of`, `below`, `above` | `<<`, `>>`, `<<\|`, `\|>>` |
| `overleft`, `overright`, `overbelow`, `overabove` | `&<`, `&>`, `&<\|`, `\|&>` |
| `knn(x)` | `<->` (index-assisted in `ORDER BY`) |
| `bbox_distance(x)`, `knn_nd(x)` | `<#>`, `<<->>` |

```python
nearest = Area.select().order_by(Area.geom.knn(shapely.Point(10.7, 59.9))).limit(5)
assert "<->" in nearest.sql()[0]
```
