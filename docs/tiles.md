# Vector tiles and Martin

[Martin](https://maplibre.org/martin/sources-pg-functions.html) serves tiles from SQL
functions `fn(z integer, x integer, y integer, query_params json) RETURNS bytea`.
`pg.to_tile_fn` builds one from a peewee select.

```python
import peewee as pw

import peewee_gis as pg

db = pw.PostgresqlDatabase(None)


class Grid(pw.Model):
    ssbid = pw.BigIntegerField()
    year = pw.IntegerField()
    kind = pw.TextField()
    value = pw.FloatField()
    geom = pg.GeometryField(pg.GeomType.Polygon, srid=4326, index=True)

    class Meta:
        database = db
        schema = "tiles"


tiles = pg.TileRegistry()


@tiles.to_tile_fn(Grid._meta.schema, feature_id="ssbid")
def grid(z, x, y, kind: str, year: int = pw.fn.date_part("year", pw.fn.now())):
    """Statistics per SSB grid cell."""
    return Grid.select(Grid.ssbid, Grid.value, Grid.geom).where(Grid.year == year, Grid.kind == kind)


ddl = db.get_sql_context().sql(grid).query()[0]
assert ddl.startswith('CREATE OR REPLACE FUNCTION "tiles"."grid"(z integer, x integer, y integer, query_params json)')
```

* The decorated function gets `z`, `x`, `y` and its parameters as SQL expressions and
  returns a select with **one geometry column**; every other selected column becomes a
  feature property (expressions need an `.alias()`).
* Parameters after `z, x, y` come from Martin's `query_params`, the URL query string
  (`/tiles.grid/8/135/74?kind=pop&year=2023`). They are cast to their annotation (`int`,
  `float`, `str`, `bool`, `date`, or an SQL type name such as `"bigint"`), and defaults
  (python values or peewee expressions) apply when absent. A trailing `_` is dropped from
  the key, so `type_` reads `type`.
* `feature_id` becomes the MVT feature id (cast to `bigint`). `feature_mode="move"` drops it
  from the properties.
* Geometries are transformed to web mercator, simplified to one pixel at the tile's zoom
  (`simplify=False` to disable, or a tolerance), and clipped with `ST_AsMVTGeom`. Rows are
  filtered with `&&` against the buffered tile envelope in the column's SRID, so the spatial
  index is used.
* The function is `STABLE PARALLEL SAFE` (it reads tables, so not `IMMUTABLE`); override with
  `volatility=pg.Volatility.VOLATILE` etc.

## Creating and using

```py
tiles.create_all(db)  # CREATE OR REPLACE FUNCTION + COMMENT for each
grid.create(db)  # one
db.execute(grid.drop())
mvt = grid.tile(db, 8, 135, 74, kind="pop")  # call the SQL function: bytes
grid.query(8, 135, 74, kind="pop")  # the same query standalone (no function needed)
```

`pg.tile_query(select, z, x, y, layer=...)` is the query builder on its own, e.g. for serving
tiles from your own web app.

### What is safe to put in the query

Martin's `query_params` (the URL query string, controlled by whoever requests tiles) only
reach the query as the decorated function's parameters: the key is a bound value, the value
is cast to the annotated type inside the SQL function, and it is data, never SQL.

The function body itself is SQL text: values written into the query when it is *defined*
(`.where(Grid.kind == "pop")`, parameter defaults) are inlined as literals, because a
function body can't take bound parameters. peewee quotes strings, bytes and dates; other
types are inserted with `str()`. Build tile functions (and materialized views, which work
the same way) at deploy time from your own code, never from request data; values that vary
per request belong in `query_params`.

## TileJSON and Martin's config

`create()` stores TileJSON in `COMMENT ON FUNCTION`; Martin merges it into the source's
TileJSON. It lists the layer's fields with their types and the query parameters:

```python
assert grid.tilejson()["vector_layers"] == [{"id": "grid", "fields": {"ssbid": "Number", "value": "Number"}}]
```

Martin's config can list the functions explicitly, so they are served whatever schema they
are in (no `auto_publish` needed):

```python
config = tiles.martin_config(connection_string="${DATABASE_URL}")
assert config["postgres"]["functions"] == {"tiles.grid": {"schema": "tiles", "function": "grid"}}
```

Write it as YAML with any YAML library, e.g. [PyYAML](https://pypi.org/project/PyYAML/):

```python
import yaml

text = yaml.safe_dump(config, sort_keys=False)
assert "connection_string: ${DATABASE_URL}\n" in text  # unquoted
```

Not as JSON: Martin only expands `${DATABASE_URL}` in an *unquoted* YAML value (checked with
Martin 1.16.1), and JSON quotes every string, so a JSON config only works with the password
written into it.

## Scale helpers

`pg.tiles.pixel_size(z, pixels=512)` is the web mercator width of a pixel at zoom `z`;
`pg.tiles.ground_width(z, latitude)` the width of a tile on the ground in metres.
