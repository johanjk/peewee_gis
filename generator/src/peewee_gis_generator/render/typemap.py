"""Map PostgreSQL types (as written in the PostGIS manual) to python annotations."""

import keyword
import re

SCALARS = {
    "integer": "int",
    "int": "int",
    "int4": "int",
    "int8": "int",
    "bigint": "int",
    "smallint": "int",
    "float": "float",
    "float8": "float",
    "double precision": "float",
    "text": "str",
    "varchar": "str",
    "name": "str",
    "character": "str",
    "cstring": "str",
    "regclass": "str",
    "regprocedure": "str",
    "boolean": "bool",
    "bool": "bool",
    "bytea": "bytes",
}

# SQL-only types: marker classes in peewee_gis.sqltypes
MARKERS = {
    "geometry": "geometry",
    "point": "geometry",
    "geography": "geography",
    "box2d": "box2d",
    "box3d": "box3d",
    "raster": "raster",
    "json": "json",
    "jsonb": "json",
    "spheroid": "spheroid",
    "record": "record",
}

# Values returned to python with a converter (see peewee_gis.st.convert)
CATEGORIES = {
    "geometry": "geometry",
    "point": "geometry",
    "geography": "geography",
    "box2d": "box2d",
    "box3d": "box3d",
    "raster": "raster",
}

LITERALS = {
    "geometry": "Geom",
    "geography": "Geom",
    "json": "str | dict[str, Any]",
    "spheroid": "str",
}


def base(t: str) -> tuple[str, int]:
    """Strip set-ness and arrays: ``'setof geometry[]'`` -> ``('geometry', 1)``."""
    t = t.strip().removeprefix("setof ").strip()
    t = re.sub(r"\s+(win)?set$", "", t)
    dims = t.count("[]")
    return t.replace("[]", "").strip(), dims


def marker(t: str) -> str:
    """Type parameter of ``StChain[...]`` for a value of SQL type ``t``."""
    if t == "void":
        return "None"
    b, dims = base(t)
    if b.startswith("("):  # anonymous composite: (geometry, double precision)
        m = "record"
    elif b == "anyelement":
        m = "Any"
    else:
        m = SCALARS.get(b) or MARKERS.get(b) or "record"  # named composites
    for _ in range(dims):
        m = f"list[{m}]"
    return m


def category(t: str) -> str:
    """Runtime conversion category of a value of SQL type ``t``."""
    b, dims = base(t)
    if dims:
        return "other"
    return CATEGORIES.get(b, "other")


def argument(t: str) -> str:
    """Annotation of an argument of SQL type ``t``: python literal or any peewee node."""
    b, dims = base(t)
    if b.startswith("(") or b in {"anyelement", "record"}:
        return "Any"
    lit = SCALARS.get(b) or LITERALS.get(b)
    if lit is None:
        return "Arg[None]"  # only nodes, e.g. box2d, raster, composites
    for _ in range(dims):
        lit = f"Sequence[{lit}]"
    return f"Arg[{lit}]"


def py_identifier(name: str) -> str:
    name = re.sub(r"\W", "_", name.strip())
    if not name or name[0].isdigit():
        name = f"_{name}"
    if keyword.iskeyword(name) or keyword.issoftkeyword(name):
        name = f"{name}_"
    return name


def py_name(sql_name: str) -> str:
    """Attribute name on ``st`` for an SQL function name.

    ``ST_Area`` -> ``Area``, ``ST_3DArea`` -> ``n3DArea``; other names are kept
    (``Box2D``, ``CG_3DArea``, ``postgis_srs``).
    """
    if sql_name.upper().startswith("ST_"):
        name = sql_name[3:]
        if name[0].isdigit():
            name = f"n{name}"
        return py_identifier(name)
    return py_identifier(sql_name)
