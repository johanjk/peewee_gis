"""``CREATE FUNCTION`` / ``DROP FUNCTION`` / ``COMMENT ON FUNCTION`` for SQL functions with a peewee body."""

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, override

import peewee as pw

from .names import entity


class Volatility(StrEnum):
    """Function volatility. Functions reading tables must not be ``IMMUTABLE``."""

    IMMUTABLE = "IMMUTABLE"
    STABLE = "STABLE"
    VOLATILE = "VOLATILE"


class Parallel(StrEnum):
    SAFE = "PARALLEL SAFE"
    RESTRICTED = "PARALLEL RESTRICTED"
    UNSAFE = "PARALLEL UNSAFE"


def render_literal_sql(ctx: pw.Context, node: pw.Node) -> str:
    """``node`` as SQL with values inlined, e.g. for a function body.

    ``%`` is doubled: the statement is executed with an empty parameter list.
    """
    sub = ctx.as_new()
    with sub(value_literals=True):
        sub.sql(node)
    text, params = sub.query()
    if params:  # pragma: no cover - value_literals inlines everything
        msg = f"function body has unbound parameters: {params!r}"
        raise ValueError(msg)
    return text.replace("%", "%%")


@dataclass(eq=False)
class FunctionSignature:
    """Name and typed arguments of an SQL function."""

    name: str
    args: list[tuple[str, str]]
    """``(name, sql type)``."""
    returns: str
    schema: str | None = None

    def ref(self) -> pw.NodeList:
        """``"schema"."name"(integer, ...)``, for DROP/COMMENT."""
        return pw.NodeList(
            [entity(self.schema, self.name), pw.SQL(f"({', '.join(t for _, t in self.args)})")],
            glue="",
        )


@dataclass(eq=False)
class CreateFunction(pw.Node):
    """``CREATE OR REPLACE FUNCTION ... LANGUAGE sql STABLE PARALLEL SAFE AS $body$ <query> $body$``.

    The body's values are inlined as SQL literals, and argument types, ``returns``,
    ``language`` and ``extra`` are written as given: build it from your own code, not
    from user input.
    """

    signature: FunctionSignature
    body: pw.Node | str
    language: str = "sql"
    volatility: Volatility = Volatility.STABLE
    parallel: Parallel = Parallel.SAFE
    strict: bool = False
    replace: bool = True
    extra: list[str] = field(default_factory=list[str])

    @override
    def __sql__(self, ctx: pw.Context) -> pw.Context:
        sig = self.signature
        body = self.body if isinstance(self.body, str) else render_literal_sql(ctx, self.body)
        tag = "$body$"
        if tag in body:
            msg = "function body contains $body$"
            raise ValueError(msg)
        ctx.literal("CREATE OR REPLACE FUNCTION " if self.replace else "CREATE FUNCTION ")
        ctx.sql(entity(sig.schema, sig.name))
        ctx.literal("(" + ", ".join(f"{n} {t}" for n, t in sig.args) + ")")
        ctx.literal(f" RETURNS {sig.returns} LANGUAGE {self.language} {self.volatility.value}")
        if self.strict:
            ctx.literal(" STRICT")
        ctx.literal(f" {self.parallel.value}")
        for clause in self.extra:
            ctx.literal(f" {clause}")
        return ctx.literal(f" AS {tag}\n{body}\n{tag}")


@dataclass(eq=False)
class DropFunction(pw.Node):
    signature: FunctionSignature
    if_exists: bool = True

    @override
    def __sql__(self, ctx: pw.Context) -> pw.Context:
        ctx.literal("DROP FUNCTION IF EXISTS " if self.if_exists else "DROP FUNCTION ")
        return ctx.sql(self.signature.ref())


@dataclass(eq=False)
class CommentOnFunction(pw.Node):
    """``COMMENT ON FUNCTION ... IS '<text>'``; dicts are stored as JSON (Martin reads TileJSON from it)."""

    signature: FunctionSignature
    comment: str | dict[str, Any] | None

    @override
    def __sql__(self, ctx: pw.Context) -> pw.Context:
        ctx.literal("COMMENT ON FUNCTION ").sql(self.signature.ref()).literal(" IS ")
        if self.comment is None:
            return ctx.literal("NULL")
        text = self.comment if isinstance(self.comment, str) else json.dumps(self.comment, sort_keys=True)
        return ctx.literal("'" + text.replace("'", "''").replace("%", "%%") + "'")
