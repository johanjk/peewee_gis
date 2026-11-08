# peewee_gis-stubs

Typing and docstrings for [peewee_gis](https://github.com/johanjk/peewee_gis): signatures of
every PostGIS function on `peewee_gis.st`, with the description from the PostGIS manual.

It is a [PEP 561](https://peps.python.org/pep-0561/) *partial* stub package: type checkers
and editors (pyright/Pylance, mypy, ty) combine it with peewee_gis' inline types. Nothing
imports it at runtime.

Install it where code is written and type checked, not in production:

```sh
pip install "peewee_gis[typing]"      # dev / CI: peewee_gis + peewee_gis-stubs
pip install peewee_gis                # production: runtime only
```

or as a development dependency, e.g. with uv: `uv add --dev peewee_gis-stubs`.

Without it everything works the same at runtime; `st.<function>` is just untyped (no
completion, no docstrings, no checks).

Install the same version as peewee_gis: both are built from the same PostGIS snapshot.
