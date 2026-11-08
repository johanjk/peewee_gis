"""PostGIS functions: ``st.Transform(geom, 4326)`` or ``Model.geom.st.Transform(4326)``."""

from typing import TYPE_CHECKING, cast

from .function import Bound, Cast, GeographyCast, GeometryCast, NamedArgument, Root, STFunction

if TYPE_CHECKING:
    from ._generated.api import ChainMethods, StBound, StChain, StRoot
else:
    # runtime names for annotations; typing comes from api.pyi (StChain[float] etc.)
    StChain = STFunction
    ChainMethods = STFunction
    StBound = Bound
    StRoot = Root

st: StRoot = cast("StRoot", Root())
"""All PostGIS functions; typed and documented by the generated ``api.pyi``."""

__all__ = [
    "Bound",
    "Cast",
    "ChainMethods",
    "GeographyCast",
    "GeometryCast",
    "NamedArgument",
    "Root",
    "STFunction",
    "StBound",
    "StChain",
    "StRoot",
    "st",
]
