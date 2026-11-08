"""Martin configuration for tile functions.

Listing function sources explicitly avoids depending on ``auto_publish`` and on
the schema the functions happen to be created in.
https://maplibre.org/martin/config-file.html
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .function import TileFunction


def martin_config(
    functions: Iterable[TileFunction],
    *,
    connection_string: str = "${DATABASE_URL}",
    auto_publish: bool = False,
    default_srid: int | None = None,
) -> dict[str, Any]:
    """``{"postgres": {...}}`` with one ``functions`` entry per tile function.

    Martin expands ``${VAR}`` in its config, so the connection string can stay out of the
    file, but only in unquoted YAML values: write the dict as YAML, e.g.
    ``yaml.safe_dump(config, sort_keys=False)``, not as JSON (JSON quotes the placeholder,
    and Martin then reads it literally).
    """
    postgres: dict[str, Any] = {
        "connection_string": connection_string,
        "auto_publish": auto_publish,
        "functions": {fn.source_id: fn.martin_source() for fn in functions},
    }
    if default_srid is not None:
        postgres["default_srid"] = default_srid
    return {"postgres": postgres}
