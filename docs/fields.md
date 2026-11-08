# Fields

```python
import peewee as pw
import shapely

import peewee_gis as pg
from peewee_gis import Dim, GeomType


class Place(pw.Model):
    point = pg.GeometryField(GeomType.Point, srid=4326, index=True)  # geometry(Point, 4326) + GIST
    terrain = pg.GeometryField(GeomType.Polygon, srid=25833, dim=Dim.XYZ, null=True)  # PolygonZ
    anything = pg.GeometryField(srid=0, null=True)  # geometry, no typmod
    geog = pg.GeographyField(GeomType.Point, null=True)  # geography(Point, 4326)
```

`srid` takes an `int`, or any object with `.to_epsg()` such as a `pyproj.CRS`.

## Values

Writes accept shapely geometries, WKT, EWKT (`SRID=4326;POINT(...)`), (E)WKB bytes or hex,
GeoJSON dicts/strings, and objects with `__geo_interface__`. Reads return shapely geometries
with the SRID set.

A geometry carrying another SRID than the column raises by default:

```python
moved = pg.GeometryField(GeomType.Point, srid=25833, on_srid_mismatch="transform")
```

`"transform"` wraps the value in `ST_Transform`, `"relabel"` keeps the coordinates and sets
the column's SRID. Geometries without SRID get the column's.

## Columns in queries

* `.st`: PostGIS functions (`Place.point.st.Buffer(10)`);
* `.x`, `.y`, `.z`, `.m`: `ST_X(...)` etc.;
* `.as_geography()`, `.as_geometry()`;
* the bounding box operators, see [functions](functions.md#operators).

Composite GIST indexes (geometry plus other columns) need `pg.gist_index`; peewee's
`Meta.indexes` tuples silently create a btree index, see [helpers](helpers.md).
