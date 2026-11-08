"""Quoted SQL identifiers: ``"schema"."name"`` with embedded ``"`` doubled."""

import re

import peewee as pw

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def entity(schema: str | None, name: str) -> pw.Entity:
    """``"schema"."name"``, or ``"name"`` without a schema; peewee escapes the quotes."""
    return pw.Entity(schema, name) if schema else pw.Entity(name)


def quote_ident(*parts: str | None) -> str:
    """``"a"."b"`` as a string, for SQL that is not built from peewee nodes; ``None`` parts are skipped."""
    return ".".join('"' + p.replace('"', '""') + '"' for p in parts if p is not None)


def check_identifier(name: str, what: str = "identifier") -> str:
    """``name`` if it is a plain unquoted SQL identifier (``ST_3DArea``), else ``ValueError``."""
    if not _IDENT.match(name):
        msg = f"invalid {what} {name!r}"
        raise ValueError(msg)
    return name
