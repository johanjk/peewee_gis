"""``CREATE EXTENSION``."""

from typing import TYPE_CHECKING, override

import peewee as pw

if TYPE_CHECKING:
    from collections.abc import Iterable


class CreateExtension(pw.Node):
    """``CREATE EXTENSION IF NOT EXISTS "name" [SCHEMA "schema"] [CASCADE]``."""

    def __init__(self, name: str, *, schema: str | None = None, cascade: bool = False) -> None:
        super().__init__()
        self.name = name
        self.schema = schema
        self.cascade = cascade

    @override
    def __sql__(self, ctx: pw.Context) -> pw.Context:
        ctx.literal("CREATE EXTENSION IF NOT EXISTS ").sql(pw.Entity(self.name))
        if self.schema:
            ctx.literal(" SCHEMA ").sql(pw.Entity(self.schema))
        if self.cascade:
            ctx.literal(" CASCADE")
        return ctx


def extension(name: str = "postgis", *, schema: str | None = None, cascade: bool = False) -> CreateExtension:
    """``db.execute(extension())``; e.g. ``extension("btree_gist")`` for composite GIST indexes."""
    return CreateExtension(name, schema=schema, cascade=cascade)


def create_extensions(
    database: pw.Database,
    names: Iterable[str] = ("postgis",),
    *,
    schema: str | None = None,
    cascade: bool = False,
) -> None:
    """Create several extensions, one statement each."""
    for name in names:
        database.execute(CreateExtension(name, schema=schema, cascade=cascade))
