"""Access to peewee internals that its stubs don't declare."""

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import peewee as pw


def returning(q: pw.SelectQuery) -> list[pw.Node]:
    """Selected columns/expressions of a select."""
    return list(getattr(q, "_returning", None) or ())


def alias_name(node: pw.Alias) -> str:
    return str(cast("Any", node)._alias)  # ruff: ignore[SLF001]


def index_name(index: pw.ModelIndex) -> str:
    return str(cast("Any", index)._name)  # ruff: ignore[SLF001]


def set_conversion(node: pw.Node, *, coerce: bool, python_value: Any = None) -> None:
    """Set how peewee converts a selected function's result."""
    n = cast("Any", node)
    n._coerce = coerce  # ruff: ignore[SLF001]
    n._python_value = python_value  # ruff: ignore[SLF001]


def set_converter(node: pw.ColumnBase, converter: Any) -> None:
    """``ColumnBase._converter``: result converter of a selected node."""
    cast("Any", node)._converter = converter  # ruff: ignore[SLF001]
