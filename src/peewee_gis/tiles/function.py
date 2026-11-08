"""SQL tile functions for Martin: ``fn(z integer, x integer, y integer, query_params json) RETURNS bytea``.

https://maplibre.org/martin/sources-pg-functions.html

::

    @pg.to_tile_fn("tiles", feature_id="ssbid")
    def grid(z, x, y, year: int = pw.fn.date_part("year", pw.fn.now())) -> pw.SelectQuery:
        return Grid.select(Grid.ssbid, Grid.value, Grid.geom).where(Grid.year == year)


    db.execute(grid)  # CREATE OR REPLACE FUNCTION "tiles"."grid"(...)
    grid.create(db)  # ... and COMMENT ON FUNCTION with TileJSON for Martin
    grid.tile(db, 3, 4, 2, year=2024)  # call it: MVT bytes

Extra parameters after ``z, x, y`` are read from Martin's ``query_params`` (the URL
query string, ``?year=2024``), cast to their annotation and defaulted with
``coalesce``. A trailing ``_`` is dropped from the key (``type_`` reads ``type``).
"""

import datetime
import decimal
import inspect
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, overload, override

import peewee as pw

from .._ddl import (
    CommentOnFunction,
    CreateFunction,
    DropFunction,
    FunctionSignature,
    Parallel,
    Volatility,
    quote_ident,
)
from .query import FeatureMode, Simplify, output_name, selected_columns, selected_nodes, tile_query

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


class TileQueryFn(Protocol):
    """``(z, x, y, **params) -> select``; ``z``, ``x``, ``y`` and params are SQL nodes when building the function."""

    __name__: str

    def __call__(self, z: Any, x: Any, y: Any, /, *args: Any, **kwargs: Any) -> pw.Select: ...


PY_SQL_TYPES: dict[type, str] = {
    bool: "boolean",
    int: "integer",
    float: "double precision",
    decimal.Decimal: "numeric",
    str: "text",
    datetime.date: "date",
    datetime.datetime: "timestamptz",
}

TILE_ARGS = [("z", "integer"), ("x", "integer"), ("y", "integer"), ("query_params", "json")]


def sql_type(annotation: object) -> str | None:
    """``int`` -> ``integer``; ``"bigint"`` -> ``bigint``; unannotated -> ``None`` (text)."""
    if annotation is inspect.Parameter.empty:
        return None
    if isinstance(annotation, str):
        # `from __future__ import annotations`: names of python types
        named = {t.__name__: s for t, s in PY_SQL_TYPES.items()}
        return named.get(annotation, annotation)
    if isinstance(annotation, type) and annotation in PY_SQL_TYPES:
        return PY_SQL_TYPES[annotation]
    meta = getattr(annotation, "__metadata__", None)  # Annotated[int, "smallint"]
    if meta and isinstance(meta[0], str):
        return meta[0]
    msg = f"unsupported annotation {annotation!r} for a tile query parameter; use a python type or an SQL type name"
    raise TypeError(msg)


@dataclass(frozen=True, slots=True)
class QueryParam:
    """Parameter of the decorated function read from ``query_params``."""

    name: str
    key: str
    sql_type: str | None
    default: Any = inspect.Parameter.empty

    @property
    def required(self) -> bool:
        return self.default is inspect.Parameter.empty

    def node(self, query_params: pw.Node) -> pw.Node:
        value: pw.Node = pw.Expression(query_params, "->>", pw.Value(self.key, converter=False), flat=True)
        if self.sql_type is not None:
            value = pw.Cast(value, self.sql_type)
        if not self.required:
            value = pw.fn.coalesce(value, self.default)
        return value

    def tilejson_doc(self) -> str:
        t = self.sql_type or "text"
        if self.required:
            return f"{self.key} ({t})"
        default = self.default
        if isinstance(default, pw.Node):
            default = pw.PostgresqlDatabase(None).get_sql_context(value_literals=True).sql(default).query()[0]
        else:
            default = repr(default)
        return f"{self.key} ({t}, default {default})"


def query_params(fn: Callable[..., Any]) -> list[QueryParam]:
    fname = getattr(fn, "__name__", repr(fn))
    sig = inspect.signature(fn, eval_str=False)
    names = list(sig.parameters)
    if names[:3] != ["z", "x", "y"]:
        msg = f"{fname}: the first three parameters must be (z, x, y), got {names[:3]}"
        raise TypeError(msg)
    out: list[QueryParam] = []
    for name in names[3:]:
        p = sig.parameters[name]
        if p.kind in {p.VAR_POSITIONAL, p.VAR_KEYWORD}:
            msg = f"{fname}: *args/**kwargs are not supported"
            raise TypeError(msg)
        out.append(
            QueryParam(name=name, key=name.removesuffix("_"), sql_type=sql_type(p.annotation), default=p.default),
        )
    return out


def tilejson_field_type(node: object) -> str:
    """TileJSON ``vector_layers[].fields`` type of a selected column."""
    while isinstance(node, (pw.Alias, pw.Cast)):
        node = node.node
    if isinstance(node, (pw.IntegerField, pw.FloatField, pw.DecimalField)):
        return "Number"
    if isinstance(node, pw.BooleanField):
        return "Boolean"
    return "String"


@dataclass(eq=False)
class TileFunction(pw.Node):
    """A Martin function source; executing it creates (or replaces) the SQL function."""

    fn: TileQueryFn
    schema: str | None
    name: str
    layer: str
    feature_id: str | None = None
    feature_mode: FeatureMode = "append"
    geom: str | None = None
    srid: int | None = None
    extent: int = 4096
    buffer: int = 64
    clip: bool = True
    simplify: Simplify = True
    pixels: int = 512
    volatility: Volatility = Volatility.STABLE
    parallel: Parallel = Parallel.SAFE
    minzoom: int | None = None
    maxzoom: int | None = None
    description: str | None = None
    params: list[QueryParam] = field(init=False)

    def __post_init__(self) -> None:
        self.params = query_params(self.fn)
        if self.description is None and self.fn.__doc__:
            self.description = inspect.cleandoc(self.fn.__doc__).split("\n\n")[0]

    # -- SQL
    @property
    def signature(self) -> FunctionSignature:
        return FunctionSignature(name=self.name, args=TILE_ARGS, returns="bytea", schema=self.schema)

    def _arg(self, name: str) -> pw.Node:
        # qualified with the function name: a column `x` or `z` would win over an unqualified argument
        return pw.SQL(f"{quote_ident(self.name)}.{name}")

    def inner_query(self, z: object, x: object, y: object, params: dict[str, pw.Node]) -> pw.Select:
        return self.fn(z, x, y, **params)

    def query(self, z: int | None = None, x: int | None = None, y: int | None = None, **values: object) -> pw.Select:
        """The tile query.

        Without arguments it references the function's own arguments (the function
        body); with ``z, x, y`` and parameter values it runs standalone.
        """
        zxy: tuple[int | pw.Node, int | pw.Node, int | pw.Node]
        if z is None or x is None or y is None:
            qp = self._arg("query_params")
            params = {p.name: p.node(qp) for p in self.params}
            zxy = (self._arg("z"), self._arg("x"), self._arg("y"))
        else:
            params = {}
            for p in self.params:
                if p.key in values or p.name in values:
                    v = values.get(p.key, values.get(p.name))
                    params[p.name] = pw.Cast(pw.Value(v), p.sql_type) if p.sql_type else pw.Value(v)
                elif p.required:
                    msg = f"missing tile parameter {p.key!r}"
                    raise TypeError(msg)
                else:
                    params[p.name] = p.default
            zxy = (z, x, y)
        inner = self.inner_query(zxy[0], zxy[1], zxy[2], params)
        return tile_query(
            inner,
            *zxy,
            layer=self.layer,
            geom=self.geom,
            srid=self.srid,
            feature_id=self.feature_id,
            feature_mode=self.feature_mode,
            extent=self.extent,
            buffer=self.buffer,
            clip=self.clip,
            simplify=self.simplify,
            pixels=self.pixels,
        )

    def definition(self) -> CreateFunction:
        return CreateFunction(
            signature=self.signature,
            body=self.query(),
            volatility=self.volatility,
            parallel=self.parallel,
        )

    @override
    def __sql__(self, ctx: pw.Context) -> pw.Context:
        return ctx.sql(self.definition())

    def drop(self) -> DropFunction:
        return DropFunction(self.signature)

    def comment(self) -> CommentOnFunction:
        return CommentOnFunction(self.signature, self.tilejson())

    def create(self, database: pw.Database) -> None:
        """``CREATE OR REPLACE FUNCTION`` and its TileJSON comment."""
        with database.atomic():
            database.execute(self)
            database.execute(self.comment())

    def tile(self, database: pw.Database, z: int, x: int, y: int, **params: object) -> bytes:
        """Call the created SQL function: ``SELECT schema.fn(z, x, y, '<json>')``."""
        import json  # ruff: ignore[PLC0415]

        call = pw.Function(self._qualified_name(), [z, x, y, pw.Cast(pw.Value(json.dumps(params)), "json")])
        row = database.execute(pw.Select(columns=[call])).fetchone()
        return bytes(row[0]) if row and row[0] is not None else b""

    def _qualified_name(self) -> str:
        return quote_ident(self.schema, self.name)

    # -- Martin
    @property
    def source_id(self) -> str:
        """Martin's default ``source_id_format``, ``{schema}.{function}``."""
        return f"{self.schema}.{self.name}" if self.schema else self.name

    def fields(self) -> dict[str, str]:
        """Feature properties and their TileJSON types."""
        inner = self.inner_query(pw.SQL("0"), pw.SQL("0"), pw.SQL("0"), {p.name: pw.SQL("NULL") for p in self.params})
        sel = selected_columns(inner, self.geom)
        types = {output_name(node): tilejson_field_type(node) for node in selected_nodes(inner)}
        return {
            name: types.get(name, "String")
            for name in sel.properties
            if not (name == self.feature_id and self.feature_mode == "move")
        }

    def tilejson(self) -> dict[str, Any]:
        """TileJSON stored in ``COMMENT ON FUNCTION``; Martin merges it into the source's TileJSON."""
        doc: dict[str, Any] = {"vector_layers": [{"id": self.layer, "fields": self.fields()}]}
        desc = [self.description] if self.description else []
        if self.params:
            desc.append("Query parameters: " + ", ".join(p.tilejson_doc() for p in self.params))
        if desc:
            doc["description"] = ". ".join(d.rstrip(".") for d in desc)
        if self.minzoom is not None:
            doc["minzoom"] = self.minzoom
        if self.maxzoom is not None:
            doc["maxzoom"] = self.maxzoom
        return doc

    def martin_source(self) -> dict[str, Any]:
        """Entry for ``postgres.functions`` in Martin's config."""
        src: dict[str, Any] = {"schema": self.schema or "public", "function": self.name}
        if self.minzoom is not None:
            src["minzoom"] = self.minzoom
        if self.maxzoom is not None:
            src["maxzoom"] = self.maxzoom
        return src


@overload
def to_tile_fn(
    schema: str | None,
    *,
    name: str | None = ...,
    **kwargs: Any,
) -> Callable[[TileQueryFn], TileFunction]: ...
@overload
def to_tile_fn(schema: TileQueryFn, /) -> TileFunction: ...
def to_tile_fn(
    schema: str | TileQueryFn | None = None,
    *,
    name: str | None = None,
    layer: str | None = None,
    feature_id: str | None = None,
    feature_mode: FeatureMode = "append",
    **kwargs: Any,
) -> Callable[[TileQueryFn], TileFunction] | TileFunction:
    """Decorate ``(z, x, y, **params) -> select`` into a :class:`TileFunction`.

    Args:
        schema: schema of the SQL function (``Model._meta.schema``); ``None`` for the search path.
        name: SQL function name, defaults to the python function's.
        layer: MVT layer name, defaults to ``name``.
        feature_id: column used as feature id.
        feature_mode: ``"append"`` keeps the feature id as a property too; ``"move"``
            drops it from the properties.
        **kwargs: :class:`TileFunction` / :func:`tile_query` options: ``geom``, ``srid``,
            ``extent``, ``buffer``, ``clip``, ``simplify``, ``pixels``, ``volatility``,
            ``parallel``, ``minzoom``, ``maxzoom``, ``description``.
    """
    if schema is not None and not isinstance(schema, str):  # bare @to_tile_fn
        return to_tile_fn(None)(schema)

    def wrap(fn: TileQueryFn) -> TileFunction:
        n = name or fn.__name__
        return TileFunction(
            fn=fn,
            schema=schema,
            name=n,
            layer=layer or n,
            feature_id=feature_id,
            feature_mode=feature_mode,
            **kwargs,
        )

    return wrap


class TileRegistry:
    """Collects tile functions: create/drop them together and write Martin's config."""

    def __init__(self) -> None:
        super().__init__()
        self.functions: dict[str, TileFunction] = {}

    def add(self, fn: TileFunction) -> TileFunction:
        if fn.source_id in self.functions:
            msg = f"duplicate tile function {fn.source_id}"
            raise ValueError(msg)
        self.functions[fn.source_id] = fn
        return fn

    def to_tile_fn(self, schema: str | None = None, **kwargs: Any) -> Callable[[TileQueryFn], TileFunction]:
        """Like :func:`to_tile_fn`, and registered."""

        def wrap(fn: TileQueryFn) -> TileFunction:
            return self.add(to_tile_fn(schema, **kwargs)(fn))

        return wrap

    def __iter__(self) -> Iterator[TileFunction]:
        return iter(self.functions.values())

    def __len__(self) -> int:
        return len(self.functions)

    def create_all(self, database: pw.Database) -> None:
        with database.atomic():
            for fn in self:
                fn.create(database)

    def drop_all(self, database: pw.Database) -> None:
        with database.atomic():
            for fn in self:
                database.execute(fn.drop())

    def martin_config(self, **kwargs: Any) -> dict[str, Any]:
        from .martin import martin_config  # ruff: ignore[PLC0415]

        return martin_config(self, **kwargs)
