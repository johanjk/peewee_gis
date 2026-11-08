# Helpers

```python
import peewee as pw
import shapely

import peewee_gis as pg

db = pw.PostgresqlDatabase(None)


class Region(pw.Model):
    code = pw.IntegerField()
    scale = pw.IntegerField()
    geom = pg.GeometryField(pg.GeomType.MultiPolygon, srid=4326)

    class Meta:
        database = db


def sql(node):
    return db.get_sql_context().sql(node).query()
```

## Valid geometries

`pg.clean(geom, kind=3, multi=True, grid_size=None)`: `ST_MakeValid`, then
`ST_CollectionExtract` and `ST_Multi`; `grid_size` also snaps with `ST_ReducePrecision`.
Simplifying or reducing precision can create invalid geometries, so clean last.

```python
assert sql(pg.clean(Region.geom))[0] == 'ST_Multi(ST_CollectionExtract(ST_MakeValid("t1"."geom"), %s))'
```

## Indexes and layout

Geometry columns get a GIST index with `index=True`. A composite index over a geometry and
other columns needs `USING GIST` and the `btree_gist` extension; peewee's `Meta.indexes`
tuples take the index type from the last column and silently create a btree index.

```python
index = pg.gist_index(Region, Region.geom, Region.scale)
assert sql(index)[0] == 'CREATE INDEX IF NOT EXISTS "region_geom_scale" ON "region" USING GIST ("geom", "scale")'
```

```py
db.execute(pg.extension("btree_gist"))
Region.add_index(index)  # or db.execute(index)
db.execute(pg.helpers.cluster(Region, index))  # CLUSTER ... USING: rows in index order
```

## Subdivided views

Large polygons make spatial lookups and tile clipping slow. `pg.helpers.subdivided_view`
creates a materialized view with `ST_Subdivide`d pieces:

```python
view = pg.helpers.subdivided_view("region_parts", Region.select(Region.code, Region.geom), Region.geom)
assert "ST_Subdivide" in sql(view)[0]
```

`view.refresh()` and `view.drop()` give the matching statements. Like tile functions, a view
can't take bound parameters: the query's values are inlined as literals, so build views from
your own code, not from user input (see [what is safe in a tile query](tiles.md#what-is-safe-to-put-in-the-query)).

## Bulk loading

`pg.copy_geometries(Model, rows, fields, src_srid=None)` loads rows with `COPY` (psycopg 3).
With `src_srid`, geometries are staged and inserted with `ST_Transform` to the column SRID:

```py
pg.copy_geometries(Region, ((f["code"], f["geometry"]) for f in features), [Region.code, Region.geom], src_srid=25833)
```

## GeoJSON

`pg.feature_collection(select, geom="geom", id_column=None)` returns one `json`
FeatureCollection (via `ST_AsGeoJSON(record)`):

```python
q = pg.feature_collection(Region.select(Region.code, Region.geom), id_column="code")
assert "json_build_object" in sql(q)[0]
```

## Extensions

`db.execute(pg.extension("postgis"))`; `pg.create_extensions(db, ["postgis", "btree_gist"])`.
