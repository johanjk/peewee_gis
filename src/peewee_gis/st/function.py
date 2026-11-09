"""Chainable PostGIS function calls.

``st.Transform(geom, 4326)`` and ``Model.geom.st.Transform(4326)`` render the same
``ST_Transform("t1"."geom", 4326)``: when chained, the previous value is the first
argument. Attribute names map to SQL names through the generated catalog
(``Area`` -> ``ST_Area``, ``n3DDistance`` -> ``ST_3DDistance``, ``Box2D`` -> ``Box2D``).

``cg`` does the same for the SFCGAL functions (``CG_``): ``Model.geom.cg.Extrude(0, 0, 10)``
renders ``CG_Extrude(...)``. A result chains in the namespace that produced it;
``.st`` and ``.cg`` switch: ``geom.st.MakeValid().cg.Extrude(0, 0, 10).st.AsText()``.

The result of a call is converted according to its SQL type: geometry and geography
become shapely geometries, box2d/box3d tuples, everything else is left to the
database driver. ``.raw()`` turns conversion off.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Self, cast, override

import peewee as pw
import shapely

from .._ddl import check_identifier, quote_ident
from .._peewee import set_conversion, set_converter
from ..convert import CONVERTERS, Category, adapt, context_srid
from ..operators import SpatialOperators

_catalog: ModuleType | None
try:
    from ._generated import catalog as _catalog
except ImportError:  # pragma: no cover - only without a build (no generated catalog)
    _catalog = None

NAMES: dict[str, str] = dict(_catalog.NAMES) if _catalog else {}
CG_NAMES: dict[str, str] = dict(getattr(_catalog, "CG_NAMES", {})) if _catalog else {}
RETURNS: dict[str, dict[str, str]] = dict(_catalog.RETURNS) if _catalog else {}

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping
    from types import ModuleType

    from ..sqltypes import geography, geometry
    from ._generated.api import CgBound, StBound


@dataclass(frozen=True, slots=True)
class Space:
    """A function namespace: its SQL prefix and the generated attribute -> SQL name map."""

    name: str
    prefix: str
    names: Mapping[str, str]
    others: Mapping[str, tuple[str, str]] = field(default_factory=dict[str, tuple[str, str]])
    """Attribute (or upper-cased SQL name) -> ``(namespace, attribute)`` that has it:
    ``cg.AsText`` is ``st.AsText``, ``st.GenerateRoof`` and ``st.CG_3DArea`` are on ``cg``."""
    elsewhere: Mapping[str, str] = field(default_factory=dict[str, str])
    """SQL prefix -> namespace for names not in the catalog: ``CG_`` names belong on ``cg``, and no
    namespace takes a prefixed name (``st.ST_Foo`` would call ``ST_ST_Foo``)."""

    def sql_name(self, attr: str) -> str:
        """SQL function name for an attribute; ``AttributeError`` for another namespace's function."""
        if (name := self.names.get(attr)) is not None:
            return name
        if (other := self.others.get(attr) or self.others.get(attr.upper())) is None:
            for prefix, space in self.elsewhere.items():
                if attr.upper().startswith(prefix):
                    rest = attr[len(prefix) :]
                    other = (space, f"n{rest}" if rest[:1].isdigit() else rest)
        if other is not None:
            space, there = other
            if space == self.name:
                msg = f"{attr}: {space} adds the {self.prefix} prefix, use {space}.{there}"
            else:
                msg = f"{attr} is not on {self.name}: use {space}.{there}, or .{space}.{there}() on a result"
            raise AttributeError(msg)
        # not in the catalog (newer PostGIS?): the prefix, n3DFoo -> ST_3DFoo
        if len(attr) > 1 and attr[0] == "n" and attr[1].isdigit():
            attr = attr[1:]
        return f"{self.prefix}{attr}"


def _by_sql(space: str, names: Mapping[str, str]) -> dict[str, tuple[str, str]]:
    """Upper-cased SQL name -> attribute: ``st.CG_3DArea``, ``cg.ST_Area``, ``st.ST_Area`` are mistakes."""
    return {sql.upper(): (space, attr) for attr, sql in names.items()}


PREFIXES = {"ST_": "st", "CG_": "cg"}
ST = Space(
    "st",
    "ST_",
    NAMES,
    others={
        **{attr: ("cg", attr) for attr in CG_NAMES.keys() - NAMES.keys()},  # SFCGAL only: GenerateRoof
        **_by_sql("cg", CG_NAMES),
        **_by_sql("st", NAMES),
    },
    elsewhere=PREFIXES,
)
CG = Space(
    "cg",
    "CG_",
    CG_NAMES,
    others={
        **{attr: ("st", attr) for attr in NAMES.keys() - CG_NAMES.keys()},
        **_by_sql("st", NAMES),
        **_by_sql("cg", CG_NAMES),
    },
    elsewhere=PREFIXES,
)
"""SFCGAL (extension ``postgis_sfcgal``)."""


def sql_name(attr: str) -> str:
    """SQL function name for an attribute of ``st``."""
    return ST.sql_name(attr)


def category(node: object) -> str | None:
    """SQL category of a value: ``geometry``, ``geography``, ... or ``None`` if unknown."""
    if isinstance(node, shapely.Geometry):
        return "geometry"
    if isinstance(node, pw.Alias):
        node = node.node
    cat = getattr(node, "_pg_category", None)
    return cat if isinstance(cat, str) else None


def result_category(name: str, first: object) -> Category:
    """Category of ``name(first, ...)``'s result, from the generated catalog."""
    by_first = RETURNS.get(name)
    if not by_first:
        return "other"
    key = category(first) if first is not None else ""
    if key is not None and key in by_first:
        return cast("Category", by_first[key])
    results = set(by_first.values())
    return cast("Category", results.pop()) if len(results) == 1 else "other"


class NamedArgument(pw.Node):
    """PostgreSQL named notation: ``margin => 0.125``."""

    def __init__(self, name: str, value: object) -> None:
        super().__init__()
        self.name: str = check_identifier(name, "argument name")
        self.value = value

    @override
    def __sql__(self, ctx: pw.Context) -> pw.Context:
        ctx.literal(f"{self.name} => ")
        return ctx.sql(self.value if isinstance(self.value, pw.Node) else pw.Value(self.value, converter=False))


class _Namespace:
    """Resolves attributes to function calls; see :meth:`Space.sql_name`."""

    _schema: str | None
    _space: Space = ST

    def _call(self, name: str, args: Iterable[object], kwargs: Mapping[str, object]) -> STFunction:
        raise NotImplementedError

    if not TYPE_CHECKING:
        # typing comes from the generated api.pyi; unknown names are errors there

        def __getattr__(self, attr: str) -> Callable[..., STFunction]:
            if attr.startswith("_"):
                raise AttributeError(attr)
            name = self._space.sql_name(attr)

            def call(*args: object, **kwargs: object) -> STFunction:
                return self._call(name, args, kwargs)

            call.__name__ = call.__qualname__ = attr
            return call

    @override
    def __dir__(self) -> Iterable[str]:
        return [*super().__dir__(), *self._space.names]


class Root(_Namespace):
    """``st``: every PostGIS function, ``st.MakePoint(10.7, 59.9)``; ``cg``: the SFCGAL ones."""

    def __init__(self, schema: str | None = None, space: Space = ST) -> None:
        super().__init__()
        self._schema = schema
        self._space = space

    @override
    def _call(self, name: str, args: Iterable[object], kwargs: Mapping[str, object]) -> STFunction:
        return result_class(self._space)(name, args, kwargs, schema=self._schema)

    def on(self, node: object) -> StBound[Any]:
        """Functions with ``node`` as first argument: ``st.on(subq.c.geom).Area()``.

        ``CgRoot`` (``cg``) is typed with ``CgBound``.
        """
        return cast("StBound[Any]", Bound(node, schema=self._schema, space=self._space))

    __getitem__ = on

    def in_schema(self, schema: str | None) -> Self:
        """Schema-qualified calls, for PostGIS installed outside the ``search_path``."""
        return type(self)(schema, self._space)

    @override
    def __repr__(self) -> str:
        name = self._space.name
        return f"<{name} schema={self._schema!r}>" if self._schema else f"<{name}>"


class Bound(_Namespace):
    """Functions with a fixed first argument; ``Model.geom.st``."""

    def __class_getitem__(cls, item: object) -> type[Self]:
        return cls

    def __init__(self, node: object, schema: str | None = None, space: Space = ST) -> None:
        super().__init__()
        self._node = node
        self._schema = schema
        self._space = space

    @override
    def _call(self, name: str, args: Iterable[object], kwargs: Mapping[str, object]) -> STFunction:
        return result_class(self._space)(name, (self._node, *args), kwargs, schema=self._schema)

    @override
    def __repr__(self) -> str:
        return f"<{self._space.name} on {self._node!r}>"


class STFunction(SpatialOperators, _Namespace, pw.Function):
    """A PostGIS function call; further calls chain on it."""

    def __class_getitem__(cls, item: object) -> type[Self]:
        return cls

    def __init__(
        self,
        name: str,
        args: Iterable[object] = (),
        kwargs: Mapping[str, object] | None = None,
        *,
        schema: str | None = None,
    ) -> None:
        args = list(args)
        srid = context_srid(args[0]) if args else None
        args = [adapt(a, srid) for a in args]
        named = [NamedArgument(k.removesuffix("_"), adapt(v, srid)) for k, v in (kwargs or {}).items()]
        cat = result_category(name, args[0] if args else None)
        converter = CONVERTERS.get(cat)
        check_identifier(name, "function name")  # rendered unquoted: ST_3DDistance is case-insensitive
        qualified = f"{quote_ident(schema)}.{name}" if schema else name
        super().__init__(qualified, [*args, *named], coerce=converter is not None, python_value=converter)
        self._schema = schema
        self._pg_category: Category = cat

    @override
    def _call(self, name: str, args: Iterable[object], kwargs: Mapping[str, object]) -> STFunction:
        return result_class(self._space)(name, (self, *args), kwargs, schema=self._schema)

    def raw(self) -> Self:
        """Return the driver's value, without conversion to shapely/tuples."""
        clone = self.clone()
        set_conversion(clone, coerce=False)
        return clone

    @override
    def cast(self, as_type: str) -> Cast:
        return make_cast(self, as_type)

    def as_geometry(self) -> GeometryCast:
        """``CAST(... AS geometry)``."""
        return GeometryCast(self)

    def as_geography(self) -> GeographyCast:
        """``CAST(... AS geography)``; measurements in metres."""
        return GeographyCast(self)

    @property
    def st(self) -> StBound[Any]:
        """PostGIS (``ST_``) functions on this result; chaining directly does the same on ``st`` results."""
        return cast("StBound[Any]", Bound(self, schema=self._schema, space=ST))

    @property
    def cg(self) -> CgBound[Any]:
        """SFCGAL (``CG_``) functions on this result: ``geom.st.MakeValid().cg.Extrude(0, 0, 10)``."""
        return cast("CgBound[Any]", Bound(self, schema=self._schema, space=CG))


class CGFunction(STFunction):
    """An SFCGAL function call (``CG_``); further calls chain on ``cg``, ``.st`` switches back."""

    _space = CG


def result_class(space: Space) -> type[STFunction]:
    """Class of a call in ``space``: results chain in the namespace that produced them."""
    return CGFunction if space is CG else STFunction


class Cast(SpatialOperators, pw.Cast):
    """``CAST(node AS type)`` that keeps converting geometry/geography and chains via ``.st``."""

    def __init__(self, node: object, as_type: str) -> None:
        super().__init__(node, as_type)
        t = as_type.strip().lower()
        self._pg_category: Category = t if t in {"geometry", "geography"} else "other"  # type: ignore[assignment]
        if self._pg_category != "other":
            # peewee converts a selected Cast through the wrapped field/function, or `_converter`
            self._coerce = True
            set_converter(self, CONVERTERS[self._pg_category])

    @property
    def st(self) -> StBound[Any]:
        """Functions on the cast value."""
        return cast("StBound[Any]", Bound(self))

    def as_geometry(self) -> GeometryCast:
        return GeometryCast(self)

    def as_geography(self) -> GeographyCast:
        return GeographyCast(self)


class GeometryCast(Cast):
    """``CAST(node AS geometry)``."""

    def __init__(self, node: object) -> None:
        super().__init__(node, "geometry")

    @property
    @override
    def st(self) -> StBound[geometry]:
        return cast("StBound[geometry]", Bound(self))

    @property
    def cg(self) -> CgBound[geometry]:
        """SFCGAL functions on the cast value (geometry only: SFCGAL has no geography functions)."""
        return cast("CgBound[geometry]", Bound(self, space=CG))


class GeographyCast(Cast):
    """``CAST(node AS geography)``: ``geom.as_geography().st.Length()`` is in metres."""

    def __init__(self, node: object) -> None:
        super().__init__(node, "geography")

    @property
    @override
    def st(self) -> StBound[geography]:
        return cast("StBound[geography]", Bound(self))


def make_cast(node: object, as_type: str) -> Cast:
    t = as_type.strip().lower()
    if t == "geometry":
        return GeometryCast(node)
    if t == "geography":
        return GeographyCast(node)
    return Cast(node, as_type)
