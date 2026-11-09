# peewee_gis_generator

Produces the function catalog of `peewee_gis.st` and its typing from the PostGIS manual.

```
manual (HTML) --scrape--> snapshots/postgis-<v>.json --render--> catalog.py  -> peewee_gis        (runtime)
                (network,                (committed)    (jinja2)  api.pyi     -> peewee_gis-stubs  (typing + docstrings)
                 bs4)
```

| file | package | path in the repository | content |
|---|---|---|---|
| `catalog.py` | `peewee_gis` | `src/peewee_gis/st/_generated/` | python attribute -> SQL name; result type per first-argument type |
| `api.pyi` | `peewee_gis-stubs` | `stubs/peewee_gis-stubs/st/_generated/` | overloads and docstrings |

Both are gitignored and rendered by each package's hatch build hook (`hatch_build.py`,
`stubs/hatch_build.py`, both calling `peewee_gis_generator.build`), for wheel and editable
builds alike.

* **scrape** (`peewee-gis-generator scrape [VERSION] [--cache FILE] [--offline]`) lists
  the functions of the manual's reference chapters and its special functions index, and
  reads every function page: synopsis (all overloads, across the geometry and raster pages
  of a name), summary, description, see-also links, examples and deprecation notices (the
  manual's warning boxes). Core, raster and SFCGAL functions are kept; topology and tiger
  functions live in their own schemas and are left out.
* **render** (`peewee-gis-generator render OUT_DIR [--only runtime|stubs] [--snapshot FILE]`) only
  needs jinja2, so builds are reproducible and offline; `poe generate` renders both into
  place. `render/corrections.py` patches defaults the manual's synopsis leaves out.

## The typing

`api.pyi` declares

* `StRoot`: `st.X(...)` with all arguments;
* `ChainMethods[T]`: `value.st.X(...)` without the first argument, one overload per manual
  signature with `self: ChainMethods[<SQL type of the first argument>]`, so overloads are
  selected by the type of the chained value;
* `StChain[T]` (a function result) and `StBound[T]` (`Model.geom.st`).

Functions with a deprecation notice get `@deprecated("<notice>")` (PEP 702) on every
overload, and the notice opens their docstring.

The output passes the project's ruff config (`poe lint:generated`), except PYI021
(docstrings in a stub), N802/N803 (names as in PostGIS and its manual) and RUF002 (the
manual's typography). Docstrings are re-flowed to 120 columns.

Arguments accept a python literal of the matching type or any peewee node (`Arg[T]`).
Required arguments are positional-only (the manual's parameter names don't always match the
SQL ones); arguments with defaults can be passed by name.

## Updating PostGIS

```sh
# 1. set POSTGIS_VERSION in src/peewee_gis_generator/build.py (the only place; both
#    packages' build hooks, the CLI and the poe tasks read it), then
uv run poe generate:refresh                    # scrape snapshots/postgis-<version>.json
uv run poe generate
uv run poe test:generator && uv run poe types:usage
```

Commit the new snapshot and keep the older ones: functions documented in an older snapshot
but missing from the current one are rendered from the newest snapshot that has them,
marked `@deprecated` ("Not in the PostGIS 3.8 manual (last documented in 3.7).
Deprecated since 3.5.0: use CG_3DArea instead.", see `render/history.py`). Keep the
snapshots of every [supported PostGIS version](https://postgis.net/development/source_code/);
older ones can be deleted once a version is end of life.

The test database image (`.github/docker/Dockerfile`, updated by
Dependabot) is separate: it may run a newer PostGIS than the snapshot.
