"""PostGIS for the peewee ORM.

* ``st``: every PostGIS function, typed and documented from the PostGIS manual, chainable:
  ``Model.geom.st.Transform(3857).Simplify(10)``.
* ``GeometryField`` / ``GeographyField``: columns with shapely values.
* ``to_tile_fn``: Mapbox vector tile functions for Martin.
"""

from . import helpers, tiles
from ._ddl import CreateExtension, Parallel, Volatility, create_extensions, extension
from ._srid import SRID, as_srid
from .convert import literal, load_box2d, load_box3d, load_geometry
from .fields import Dim, GeographyField, GeometryField, GeomType, SpatialField, to_shapely
from .helpers import clean, copy_geometries, feature_collection, gist_index
from .operators import SpatialOperators
from .st import Cast, NamedArgument, Root, STFunction, st
from .tiles import TileFunction, TileRegistry, martin_config, tile_query, to_tile_fn

try:
    from .version import __version__
except ImportError:  # pragma: no cover
    __version__ = "0+unknown"

__all__ = [
    "SRID",
    "Cast",
    "CreateExtension",
    "Dim",
    "GeographyField",
    "GeomType",
    "GeometryField",
    "NamedArgument",
    "Parallel",
    "Root",
    "STFunction",
    "SpatialField",
    "SpatialOperators",
    "TileFunction",
    "TileRegistry",
    "Volatility",
    "__version__",
    "as_srid",
    "clean",
    "copy_geometries",
    "create_extensions",
    "extension",
    "feature_collection",
    "gist_index",
    "helpers",
    "literal",
    "load_box2d",
    "load_box3d",
    "load_geometry",
    "martin_config",
    "st",
    "tile_query",
    "tiles",
    "to_shapely",
    "to_tile_fn",
]
