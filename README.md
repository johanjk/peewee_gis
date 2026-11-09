# peewee_gis

[PostGIS](https://postgis.net) for the [peewee](https://github.com/coleifer/peewee) ORM.

* **Every PostGIS function, typed and documented.** Signatures and docstrings are generated
  from the PostGIS manual, so editors complete `Model.geom.st.Tr…` to `Transform`, show the
  manual's description, and flag wrong arity, unknown functions, or a geography-only overload
  used on a geometry. They ship separately, in [`peewee_gis-stubs`](#typing), so production
  installs don't carry them.
* **SFCGAL on `cg`**: `Model.geom.cg.Extrude(0, 0, 10).Volume()`, switching with `.st` / `.cg`.
* **Chaining instead of nesting.** `Model.geom.st.Transform(3857).Simplify(10).AsText()`
  renders `ST_AsText(ST_Simplify(ST_Transform("t1"."geom", 3857), 10))`.
* **Geometry and geography fields** with [shapely](https://shapely.readthedocs.io) values:
  SRID checks, Z/M dimensions, GIST indexes by default.
* **Vector tiles for [Martin](https://maplibre.org/martin/)**: a decorator turns a select
  into an SQL tile function `fn(z, x, y, query_params json) RETURNS bytea`.

```python
import peewee as pw
import shapely

import peewee_gis as pg

db = pw.PostgresqlDatabase("gis")


class Road(pw.Model):
    name = pw.TextField()
    geom = pg.GeometryField(pg.GeomType.LineString, srid=25833, index=True)

    class Meta:
        database = db


oslo = pg.st.SetSRID(shapely.Point(10.75, 59.91), 4326).Transform(25833)

query = (
    Road
    .select(Road.name, Road.geom.st.Length().alias("metres"))
    .where(Road.geom.st.DWithin(oslo, 1000))
    .order_by(Road.geom.knn(oslo))
)
print(query.sql())
```

Chains switch between PostGIS (`st`) and SFCGAL (`cg`, extension `postgis_sfcgal`) with
`.st` / `.cg`; each result keeps chaining in the namespace that produced it. Building
volumes from 2D footprints and a height column:

```python
class Building(pw.Model):
    height = pw.FloatField()
    footprint = pg.GeometryField(pg.GeomType.Polygon, srid=25833)

    class Meta:
        database = db


body = (
    Building.footprint.st
    .MakeValid()  # st: ST_MakeValid
    .SimplifyPreserveTopology(0.5)  # still st
    .cg.Extrude(0, 0, Building.height)  # switch to SFCGAL: CG_Extrude
    .MakeSolid()  # still cg
)
query = Building.select(
    Building.id,
    body.Volume().alias("volume"),  # CG_Volume
    body.st.ZMax().alias("top"),  # back to st: ST_ZMax
    body.st.GeometryType().alias("kind"),
)
assert query.sql()[0].startswith(
    'SELECT "t1"."id", CG_Volume(CG_MakeSolid(CG_Extrude('
    'ST_SimplifyPreserveTopology(ST_MakeValid("t1"."footprint"), %s), %s, %s, "t1"."height"))) AS "volume"'
)
# a 20 x 10 m footprint, 12.5 m high:
# [{'id': 1, 'volume': 2500.0, 'top': 12.5, 'kind': 'ST_PolyhedralSurface'}]
```

Results come back converted by SQL type: geometries as shapely objects (with their SRID),
`box2d` as tuples, numbers, booleans and text as they are.

## Install

```sh
pip install "peewee_gis[typing]"    # development: with typing and docstrings
pip install peewee_gis              # production: runtime only
```

psycopg3 is required for `copy_geometries`.

## Typing

peewee_gis is two distributions, built from the same PostGIS manual snapshot:

| | `peewee_gis` | `peewee_gis-stubs` |
|---|---|---|
| contains | the library, and a small catalog of every function's SQL name and result type | `api.pyi`: a signature per overload of every PostGIS function on `st`, with the manual's description as docstring (about 2 MB) |
| used by | your program, at runtime | editors and type checkers only; never imported |
| install | always | where code is written and checked: `peewee_gis[typing]`, or a dev dependency (`uv add --dev peewee_gis-stubs`) |

`peewee_gis-stubs` is a [PEP 561](https://peps.python.org/pep-0561/) *partial* stub
package: pyright/Pylance, mypy and ty pick it up automatically and combine it with
peewee_gis' own inline types. Install the same version as peewee_gis.

Without it nothing changes at runtime, and type checking still passes: `st.Transform(...)`
and `Model.geom.st` are just untyped (`Any`), so there is no completion, no docstrings and
no checks on PostGIS calls. Everything else (fields, tiles, helpers) stays typed.

The typing is generated for PostGIS 3.7. Functions missing from it still work
(`st.Foo(...)` renders `ST_Foo(...)`); they are untyped. See
[how the typing is generated](generator/README.md).

## Documentation

* [Functions: `st`, chaining, casts, conversion](docs/functions.md)
* [Fields](docs/fields.md)
* [Vector tiles and Martin](docs/tiles.md)
* [Helpers: indexes, cleaning, bulk loading, GeoJSON](docs/helpers.md)
* [How the typing is generated](generator/README.md)

## Development

```sh
uv sync                  # editable installs of peewee_gis and peewee_gis-stubs (stubs/); renders
                         # src/peewee_gis/st/_generated/catalog.py and stubs/.../api.pyi
uv run poe setup         # PostGIS in docker on 127.0.0.1:30000
uv run poe test          # pytest-peewee: each test in a rolled back transaction
uv run poe test:generator
uv run poe lint:ci       # deptry, ruff, pyright, ty, verifytypes, typing usage checks
uv run poe teardown
```

`uv run poe generate:refresh` re-scrapes the PostGIS manual into
`generator/snapshots/`; commit the snapshot. Builds only render from it (no network).
`uv run poe dist:all` builds and checks both distributions.
