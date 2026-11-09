"""PostGIS functions: ``st.Transform(geom, 4326)`` or ``Model.geom.st.Transform(4326)``; SFCGAL on ``cg``."""

from typing import TYPE_CHECKING, cast

from .function import (
    CG,
    Bound,
    Cast,
    CGFunction,
    GeographyCast,
    GeometryCast,
    NamedArgument,
    Root,
    STFunction,
)

if TYPE_CHECKING:
    from ._generated.api import CgBound, CgChain, CgChainMethods, CgRoot, ChainMethods, StBound, StChain, StRoot
else:
    # runtime names for annotations; typing comes from api.pyi (StChain[float] etc.)
    StChain = STFunction
    ChainMethods = STFunction
    StBound = Bound
    StRoot = Root
    CgChain = CGFunction
    CgChainMethods = CGFunction
    CgBound = Bound
    CgRoot = Root

st: StRoot = cast("StRoot", Root())
"""All PostGIS functions; typed and documented by the generated ``api.pyi``."""

cg: CgRoot = cast("CgRoot", Root(space=CG))
"""The SFCGAL functions (``CG_``, extension ``postgis_sfcgal``) without the prefix: ``cg.Extrude``."""

__all__ = [
    "Bound",
    "CGFunction",
    "Cast",
    "CgBound",
    "CgChain",
    "CgChainMethods",
    "CgRoot",
    "ChainMethods",
    "GeographyCast",
    "GeometryCast",
    "NamedArgument",
    "Root",
    "STFunction",
    "StBound",
    "StChain",
    "StRoot",
    "cg",
    "st",
]
