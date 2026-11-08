"""Mapbox vector tile queries: ``SELECT ST_AsMVT(tile, ...) FROM (<your select>) ...``.

https://postgis.net/docs/ST_AsMVT.html#id1219727 -- the canonical form::

    SELECT ST_AsMVT(tile, 'layer', 4096, 'geom', 'f_id') FROM (
        SELECT <properties>, <feature id> AS f_id, ST_AsMVTGeom(
            ST_Transform(ST_CurveToLine(q.geom), 3857), ST_TileEnvelope(z, x, y), 4096, 64, true
        ) AS geom
        FROM (<your select>) AS q
        WHERE q.geom && ST_Transform(ST_TileEnvelope(z, x, y, margin => 64.0 / 4096), <srid>)
    ) AS tile WHERE tile.geom IS NOT NULL
"""

from dataclasses import dataclass
from typing import Literal

import peewee as pw

from .._peewee import alias_name, returning
from ..fields import GeometryField
from ..st import st

WEB_MERCATOR = 3857
WORLD_WIDTH = 40075016.68
"""Width of the web mercator world (``ST_TileEnvelope(0, 0, 0)``) in metres."""

type FeatureMode = Literal["append", "move"]
type Simplify = bool | float | pw.Node


def pixel_size(z: int | pw.Node, pixels: int = 512) -> float | pw.Node:
    """Width of one pixel at zoom ``z`` in web mercator units (metres at the equator).

    A python value for an ``int`` zoom, an SQL expression for a node (e.g. a function argument).
    """
    if isinstance(z, int):
        return WORLD_WIDTH / pixels / 2**z
    return pw.Value(round(WORLD_WIDTH / pixels, 4), converter=False) / pw.fn.pow(2, z)


def ground_width(z: int, latitude: float = 0.0) -> float:
    """Width of a tile at zoom ``z`` on the ground, in metres, at ``latitude`` (web mercator scale)."""
    import math  # ruff: ignore[PLC0415]

    return WORLD_WIDTH / 2**z * math.cos(math.radians(latitude))


@dataclass(frozen=True, slots=True)
class Selected:
    """Output columns of the inner select."""

    geom: str
    srid: int
    properties: list[str]


def selected_columns(q: pw.Select, geom: str | None = None) -> Selected:
    """Names of the columns ``q`` selects, and which one is the geometry.

    The geometry is the selected :class:`GeometryField` (or a function/cast/alias of
    one, which then needs an alias), unless ``geom`` names it.
    """
    names: list[str] = []
    geoms: list[tuple[str, int]] = []
    for node in selected_nodes(q):
        name = output_name(node)
        names.append(name)
        srid = _srid(node.unwrap() if isinstance(node, pw.Alias) else node)
        if srid is not None:
            geoms.append((name, srid))

    if geom is None:
        if len(geoms) != 1:
            msg = f"select exactly one geometry column, or name it with geom=...; found {[g for g, _ in geoms]}"
            raise ValueError(msg)
        geom, srid = geoms[0]
    else:
        if geom not in names:
            msg = f"geometry column {geom!r} is not selected ({names})"
            raise ValueError(msg)
        srid = dict(geoms).get(geom, 0)
    if len(set(names)) != len(names):
        msg = f"duplicate column names in {names}"
        raise ValueError(msg)
    return Selected(geom=geom, srid=srid, properties=[n for n in names if n != geom])


def selected_nodes(q: pw.Select) -> list[pw.Node]:
    """The columns/expressions ``q`` selects."""
    return returning(q)


def output_name(node: pw.Node) -> str:
    """Name of a selected column in the result: the alias, or the column name."""
    if isinstance(node, pw.Alias):
        return alias_name(node)
    if isinstance(node, pw.Field):
        return node.column_name
    if isinstance(node, pw.Column):
        return node.name
    msg = f"give {node!r} an alias: tile properties need column names"
    raise TypeError(msg)


def _srid(node: object) -> int | None:
    """SRID of a geometry-valued node, as far as it can be known."""
    while isinstance(node, (pw.Alias, pw.Cast)):
        node = node.node
    if isinstance(node, GeometryField):
        return node.srid
    # ST_Transform(x, 4326) and friends keep the column's SRID unless transformed
    name = getattr(node, "name", "")
    args = getattr(node, "arguments", None)
    if getattr(node, "_pg_category", None) == "geometry" and args:
        if isinstance(name, str) and name.lower().endswith(("st_transform", "st_setsrid")) and len(args) > 1:
            return args[1] if isinstance(args[1], int) else None
        return _srid(args[0])
    return None


def tile_query(
    q: pw.Select,
    z: int | pw.Node,
    x: int | pw.Node,
    y: int | pw.Node,
    *,
    layer: str,
    geom: str | None = None,
    srid: int | None = None,
    feature_id: str | None = None,
    feature_mode: FeatureMode = "append",
    extent: int = 4096,
    buffer: int = 64,
    clip: bool = True,
    simplify: Simplify = True,
    pixels: int = 512,
) -> pw.Select:
    """Wrap ``q`` into a query returning one MVT (``bytea``) for tile ``z/x/y``.

    Args:
        q: select with one geometry column; every other selected column becomes a
            feature property.
        z: zoom, a python int or an SQL node (function argument).
        x: tile column.
        y: tile row.
        layer: MVT layer name.
        geom: name of the geometry column, when it can't be detected.
        srid: SRID of the geometry, when it can't be detected from the column.
        feature_id: column used as MVT feature id (cast to ``bigint``).
        feature_mode: ``"append"`` keeps the id column as a property too, ``"move"`` doesn't.
        extent: tile extent in tile coordinates, passed to ``ST_AsMVTGeom``/``ST_AsMVT``.
        buffer: buffer around the tile in tile coordinates; also widens the bbox filter.
        clip: clip geometries to the buffered tile.
        simplify: ``True`` simplifies to one pixel (``pixels`` per tile) at zoom ``z``;
            a number/node is used as tolerance in web mercator units; ``False`` disables it.
        pixels: tile size in pixels, for ``simplify=True``.
    """
    sel = selected_columns(q, geom)
    srid = srid or sel.srid
    if not srid:
        msg = "unknown SRID of the geometry column; pass srid=..."
        raise ValueError(msg)
    if feature_id is not None and feature_id not in sel.properties:
        msg = f"feature id {feature_id!r} is not selected ({sel.properties})"
        raise ValueError(msg)
    for reserved in ("f_id", "geom"):
        if reserved in sel.properties and reserved != feature_id:
            msg = f"column name {reserved!r} is reserved in tile queries; alias it"
            raise ValueError(msg)

    sub = q.alias("q")
    gcol = pw.Column(sub, sel.geom)
    props: list[pw.Node] = [
        pw.Column(sub, n) for n in sel.properties if not (n == feature_id and feature_mode == "move")
    ]
    if feature_id is not None:
        props.append(pw.Column(sub, feature_id).cast("bigint").alias("f_id"))

    tile_geom = st.on(gcol).CurveToLine().Transform(WEB_MERCATOR)
    if simplify is not False:
        tolerance = pixel_size(z, pixels) if simplify is True else simplify
        tile_geom = tile_geom.Simplify(tolerance)
    mvt_geom = tile_geom.AsMVTGeom(st.TileEnvelope(z, x, y), extent, buffer, pw.SQL("true" if clip else "false"))

    envelope = st.TileEnvelope(z, x, y, margin=pw.SQL(f"{buffer / extent!r}")).Transform(srid)
    tile = (
        pw
        .Select(from_list=[sub], columns=[*props, mvt_geom.raw().alias("geom")])
        .where(pw.Expression(gcol, "&&", envelope))
        .alias("tile")
    )
    mvt_args: list[object] = [pw.SQL("tile"), layer, extent, "geom"]
    if feature_id is not None:
        mvt_args.append("f_id")
    mvt = st.AsMVT(*mvt_args).raw()
    return pw.Select(from_list=[tile], columns=[mvt]).where(tile.c.geom.is_null(False))  # ruff: ignore[FBT003]
