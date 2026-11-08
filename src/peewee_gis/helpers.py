"""Recurring PostGIS patterns as peewee building blocks."""

import io
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, override

import peewee as pw

from ._ddl import entity, quote_ident, render_literal_sql
from ._peewee import index_name, returning
from .fields import GeometryField, SpatialField
from .st import st

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from .sqltypes import Arg, Geom, geometry
    from .st import StChain

# -- geometry hygiene


def clean(
    geom: Arg[Geom],
    *,
    kind: int | None = 3,
    multi: bool = True,
    grid_size: float | None = None,
) -> StChain[geometry]:
    """``ST_Multi(ST_CollectionExtract(ST_MakeValid(geom), kind))``, optionally snapped to ``grid_size``.

    ``kind``: 1 points, 2 lines, 3 polygons (``None`` keeps everything). Simplifying or
    reducing precision can make geometries invalid; run this last.
    """
    out = st.MakeValid(geom)
    if grid_size is not None:
        out = out.ReducePrecision(grid_size).MakeValid()
    if kind is not None:
        out = out.CollectionExtract(kind)
    if multi:
        out = out.Multi()
    return out


# -- indexes and physical layout


def gist_index(model: type[pw.Model], *fields: pw.Field, name: str | None = None) -> pw.ModelIndex:
    """GIST index over a geometry and other columns: ``Model.add_index(gist_index(Model, Model.geom, Model.scale))``.

    Non-geometry columns need ``CREATE EXTENSION btree_gist``. peewee's ``Meta.indexes``
    tuples take the index type from the last field, so ``(("geom", "scale"), False)``
    silently becomes a btree index.
    """
    if not any(isinstance(f, SpatialField) for f in fields):
        msg = "a GIST index needs a geometry/geography column"
        raise ValueError(msg)
    return pw.ModelIndex(model, fields, using="GIST", name=name)


class Cluster(pw.Node):
    """``CLUSTER "table" USING "index"``: rewrite the table in index order (locks it)."""

    def __init__(self, model: type[pw.Model], index: str) -> None:
        super().__init__()
        self.model = model
        self.index = index

    @override
    def __sql__(self, ctx: pw.Context) -> pw.Context:
        meta = self.model._meta  # ruff: ignore[SLF001]
        return (
            ctx
            .literal("CLUSTER ")
            .sql(entity(meta.schema, meta.table_name))
            .literal(" USING ")
            .sql(pw.Entity(self.index))
        )


def cluster(model: type[pw.Model], index: str | pw.ModelIndex) -> Cluster:
    return Cluster(model, index if isinstance(index, str) else index_name(index))


# -- views


class CreateMaterializedView(pw.Node):
    """``CREATE MATERIALIZED VIEW IF NOT EXISTS "schema"."name" AS <query> [WITH NO DATA]``.

    The query's values are inlined as SQL literals (a view has no parameters): build it
    from your own code, not from user input.
    """

    def __init__(self, name: str, query: pw.SelectQuery, *, schema: str | None = None, with_data: bool = True) -> None:
        super().__init__()
        self.name = name
        self.query = query
        self.schema = schema
        self.with_data = with_data

    @property
    def entity(self) -> pw.Entity:
        return entity(self.schema, self.name)

    @override
    def __sql__(self, ctx: pw.Context) -> pw.Context:
        ctx.literal("CREATE MATERIALIZED VIEW IF NOT EXISTS ").sql(self.entity).literal(" AS ")
        # views can't take bound parameters: values inlined (and `%` escaped)
        ctx.literal(render_literal_sql(ctx, self.query))
        return ctx.literal("" if self.with_data else " WITH NO DATA")

    def refresh(self, *, concurrently: bool = False) -> pw.NodeList:
        """``REFRESH MATERIALIZED VIEW [CONCURRENTLY]``; concurrently needs a unique index."""
        word = "REFRESH MATERIALIZED VIEW CONCURRENTLY" if concurrently else "REFRESH MATERIALIZED VIEW"
        return pw.NodeList([pw.SQL(word), self.entity])

    def drop(self) -> pw.NodeList:
        return pw.NodeList([pw.SQL("DROP MATERIALIZED VIEW IF EXISTS"), self.entity])


def subdivided(query: pw.Select, geom: GeometryField, *, max_vertices: int = 256) -> pw.Select:
    """Replace ``geom`` in ``query``'s selection by ``ST_Subdivide(geom, max_vertices)``: one row per piece.

    Large polygons (countries, regions) make every spatial lookup slow; subdivided
    pieces are cheap to index and to clip into tiles.
    """
    selected = returning(query)
    columns = [st.Subdivide(geom, max_vertices).alias(geom.column_name) if c is geom else c for c in selected]
    if not any(c is geom for c in selected):
        msg = f"{geom.name} is not selected"
        raise ValueError(msg)
    return query.select(*columns)


def subdivided_view(
    name: str,
    query: pw.Select,
    geom: GeometryField,
    *,
    schema: str | None = None,
    max_vertices: int = 256,
) -> CreateMaterializedView:
    """Materialized :func:`subdivided` view; give it a GIST index on the geometry."""
    return CreateMaterializedView(name, subdivided(query, geom, max_vertices=max_vertices), schema=schema)


# -- GeoJSON


def feature_collection(
    query: pw.Select,
    *,
    geom: str = "geom",
    id_column: str | None = None,
    max_decimal_digits: int = 9,
) -> pw.Select:
    """One ``json`` FeatureCollection of ``query``'s rows; other columns become properties.

    Uses ``ST_AsGeoJSON(record)`` (PostGIS 3.0+).
    """
    sub = query.alias("q")
    row = pw.SQL('"q".*')
    geojson = (
        st.AsGeoJSON(row, geom_column=geom, maxdecimaldigits=max_decimal_digits, id_column=id_column)
        if id_column is not None
        else st.AsGeoJSON(row, geom_column=geom, maxdecimaldigits=max_decimal_digits)
    )
    feature = pw.Cast(geojson.raw(), "json")
    features = pw.fn.coalesce(pw.fn.json_agg(feature), pw.SQL("'[]'::json"))

    def text(v: str) -> pw.Cast:  # json_build_object takes "any": untyped parameters don't resolve
        return pw.Cast(pw.Value(v, converter=False), "text")

    collection = pw.fn.json_build_object(text("type"), text("FeatureCollection"), text("features"), features)
    return pw.Select(from_list=[sub], columns=[collection.alias("feature_collection")])


# -- bulk loading


def _copy_text(value: object) -> str:
    if value is None:
        return r"\N"
    text = str(value)
    return text.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def copy_geometries(
    model: type[pw.Model],
    rows: Iterable[Mapping[str, Any] | Sequence[Any]],
    fields: Sequence[pw.Field],
    *,
    src_srid: int | None = None,
) -> int:
    """Bulk load ``rows`` into ``model`` with ``COPY`` (psycopg 3).

    Geometry values may be anything :class:`GeometryField` accepts. With ``src_srid``,
    geometries are loaded into a temporary staging table and inserted with
    ``ST_Transform`` to each column's SRID; without it they must already be in the
    column's SRID. Columns not listed get their database default; peewee's python-side
    ``default=`` is not applied. Returns the number of rows loaded.
    """
    database = model._meta.database  # ruff: ignore[SLF001]
    geoms = {f.name for f in fields if isinstance(f, SpatialField)}

    def encode(row: Mapping[str, Any] | Sequence[Any]) -> str:
        values: list[Any] = [row[f.name] for f in fields] if isinstance(row, Mapping) else list(row)
        out: list[str] = []
        for f, value in zip(fields, values, strict=True):
            v: object = value
            if v is not None and isinstance(f, SpatialField):
                v = f.db_value(v) if src_srid is None else _as_srid(v, src_srid, f)
                if isinstance(v, pw.Cast) and isinstance(v.node, pw.Value):
                    v = v.node.value  # the hex EWKB literal
                elif not isinstance(v, str):
                    msg = f"{f.name}: geometry in another SRID than the column; pass src_srid="
                    raise ValueError(msg)
            elif v is not None:
                v = f.db_value(v)
            out.append(_copy_text(v))
        return "\t".join(out) + "\n"

    buf = io.StringIO()
    n = 0
    for row in rows:
        buf.write(encode(row))
        n += 1
    buf.seek(0)

    table = model._meta.table_name  # ruff: ignore[SLF001]
    schema = model._meta.schema  # ruff: ignore[SLF001]
    target = quote_ident(schema, table)
    cols = ", ".join(quote_ident(f.column_name) for f in fields)

    with database.atomic():
        cursor = database.cursor()
        if src_srid is None:
            _copy(cursor, f"COPY {target} ({cols}) FROM STDIN", buf)
            return n
        # pg_temp: never resolves to (and drops) a permanent table of the same name
        staging = quote_ident("pg_temp", f"_pg_copy_{table}")
        defs = ", ".join(
            f"{quote_ident(f.column_name)} {'geometry' if f.name in geoms else _ddl_type(f)}" for f in fields
        )
        cursor.execute(f"DROP TABLE IF EXISTS {staging}")
        cursor.execute(f"CREATE TEMPORARY TABLE {staging} ({defs}) ON COMMIT DROP")
        _copy(cursor, f"COPY {staging} ({cols}) FROM STDIN", buf)
        select = ", ".join(
            f"ST_Transform({quote_ident(f.column_name)}, {int(f.srid)})"
            if isinstance(f, SpatialField)
            else quote_ident(f.column_name)
            for f in fields
        )
        cursor.execute(f"INSERT INTO {target} ({cols}) SELECT {select} FROM {staging}")  # ruff: ignore[S608]
        cursor.execute(f"DROP TABLE {staging}")  # a pg_temp table shadows a same-named real one until then
    return n


def _ddl_type(f: pw.Field) -> str:
    return str(f.ddl_datatype(None).sql)


def _as_srid(value: object, srid: int, field: SpatialField) -> str:
    import shapely  # ruff: ignore[PLC0415]

    from .convert import to_ewkb_hex  # ruff: ignore[PLC0415]
    from .fields import to_shapely  # ruff: ignore[PLC0415]

    geom = shapely.set_srid(to_shapely(value), srid)
    return to_ewkb_hex(geom, srid, output_dimension=field.dim.wkb_dimension)


def _copy(cursor: Any, statement: str, data: io.StringIO) -> None:
    if not hasattr(cursor, "copy"):
        msg = "copy_geometries needs the psycopg 3 driver (PostgresqlDatabase(..., prefer_psycopg3=True))"
        raise TypeError(msg)
    with cursor.copy(statement) as copy:
        while chunk := data.read(1 << 16):
            copy.write(chunk)
