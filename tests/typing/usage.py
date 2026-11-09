"""Type checked by `poe types:usage` (pyright), never executed.

Lines ending in `# pyright: ignore[...]` must be errors: reportUnnecessaryTypeIgnoreComment
fails the check if they are not.
"""

from typing import assert_type

import peewee as pw
import shapely

import peewee_gis as pg
from peewee_gis.sqltypes import geography, geometry
from peewee_gis.st import StBound, StChain


class Road(pw.Model):
    geom = pg.GeometryField(pg.GeomType.LineString, srid=25833)
    geog = pg.GeographyField(pg.GeomType.Point)


road = Road()
assert_type(road.geom, shapely.Geometry | None)

assert_type(Road.geom.st, StBound[geometry])
assert_type(Road.geog.st, StBound[geography])

# chains carry the SQL type of the value
assert_type(Road.geom.st.Transform(4326), StChain[geometry])
assert_type(Road.geom.st.Transform(4326).Length(), StChain[float])
assert_type(Road.geom.st.Intersects(shapely.Point(0, 0)), StChain[bool])
assert_type(pg.st.MakePoint(1, 2), StChain[geometry])
assert_type(pg.st.TileEnvelope(3, 4, 2, margin=0.1), StChain[geometry])
assert_type(Road.geom.as_geography().st.Length(), StChain[float])
assert_type(pg.st.on(pw.SQL("geom")).Area(), StChain[float])

# overloads are selected by the chained value's type
Road.geom.st.Transform(4326).Length().Transform(3857)  # pyright: ignore[reportAttributeAccessIssue]
Road.geom.st.Area(True)  # pyright: ignore[reportCallIssue]  # use_spheroid only on geography
Road.geog.st.Area(True)

# arity and names come from the manual
pg.st.Transform()  # pyright: ignore[reportCallIssue]
pg.st.NoSuchFunction(1)  # pyright: ignore[reportAttributeAccessIssue]

# casts
assert_type(Road.geom.as_geography().st, StBound[geography])
assert_type(Road.geom.cast("geography").st.Length(), StChain[float])

# deprecated in the manual: @deprecated (PEP 702), struck through in editors
rast = pw.SQL("rast")
pg.st.MapAlgebraExpr(rast, "8BUI", "[rast] * 2")  # pyright: ignore[reportDeprecated]
pg.st.MapAlgebra(rast, 1, "8BUI", "[rast] * 2")
Road.geom.st.n3DArea()  # pyright: ignore[reportDeprecated]  # SFCGAL: use CG_3DArea
Road.geom.st.CG_3DArea()
# documented in an older manual only: kept and deprecated, with the current spelling
Road.geom.st.Zmflag()  # pyright: ignore[reportDeprecated]
Road.geom.st.ZMFlag()
