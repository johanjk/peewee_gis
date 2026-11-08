"""SQL types used to parametrise chains for type checkers.

``StChain[geometry]`` is a node whose SQL value is a ``geometry``; scalars use
python types (``StChain[float]``). These classes are markers only, they are never
instantiated.
"""

from typing import Any

import peewee as pw
import shapely

type Geom = shapely.Geometry
"""Python value accepted where PostGIS expects a geometry or geography."""

type Arg[T] = T | pw.Node
"""Function argument: a python literal of type ``T`` or any peewee node."""


class geometry:
    """PostGIS ``geometry``."""


class geography:
    """PostGIS ``geography``."""


class box2d:
    """PostGIS ``box2d``."""


class box3d:
    """PostGIS ``box3d``."""


class raster:
    """PostGIS ``raster``."""


class json:
    """PostgreSQL ``json``/``jsonb``."""


class spheroid:
    """PostGIS ``spheroid``."""


class record:
    """Composite value (``geometry_dump``, ``valid_detail``, ``(geometry, float)``, ...)."""


__all__ = ["Any", "Arg", "Geom", "box2d", "box3d", "geography", "geometry", "json", "raster", "record", "spheroid"]
