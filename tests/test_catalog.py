"""The generated catalog and typing against the installed PostGIS, not only its manual.

The generator reads the manual; these tests compare what it produced with ``pg_proc`` of
the test database (the PostGIS version in ``.github/docker/Dockerfile``): every function
exists, every typed signature is callable, and results are converted by their real type.
The other way round, the installed functions no manual documents are listed.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

import peewee as pw
import pytest
from peewee_gis_generator.build import snapshot_path
from peewee_gis_generator.model import Snapshot
from peewee_gis_generator.render import history, typemap, without_topology
from peewee_gis_generator.scrape import in_scope

import peewee_gis as pg
from peewee_gis.st._generated import catalog

if TYPE_CHECKING:
    from collections.abc import Iterator

EXTENSIONS = ("postgis", "postgis_raster", "postgis_sfcgal")

UNDOCUMENTED = {
    # ST_ functions without a page in any manual since 3.2: older spellings, aliases and
    # helpers; untyped, but callable through the prefix fallback (st.PolyFromText)
    "st_approxcount",
    "st_approxhistogram",
    "st_approxquantile",
    "st_approxsummarystats",
    "st_area2d",
    "st_aswkb",
    "st_cleangeometry",
    "st_combinebbox",
    "st_findextent",
    "st_geomcollfromwkb",
    "st_geotransform",
    "st_iscoveragetile",
    "st_length2dspheroid",
    "st_mlinefromwkb",
    "st_mpointfromwkb",
    "st_mpolyfromwkb",
    "st_multilinefromwkb",
    "st_multilinestringfromtext",
    "st_multipointfromtext",
    "st_multipointfromwkb",
    "st_multipolyfromwkb",
    "st_multipolygonfromtext",
    "st_polyfromtext",
    "st_polyfromwkb",
    "st_polygonfromwkb",
    "st_setgeotransform",
    "st_symmetricdifference",
    "st_valuepercent",
    # internals: typmod and constraint helpers, install scripts, build information
    "postgis_cache_bbox",
    "postgis_constraint_dims",
    "postgis_constraint_srid",
    "postgis_constraint_type",
    "postgis_geos_noop",
    "postgis_getbbox",
    "postgis_index_supportfn",
    "postgis_lib_revision",
    "postgis_libprotobuf_version",
    "postgis_noop",
    "postgis_raster_scripts_installed",
    "postgis_sfcgal_noop",
    "postgis_sfcgal_scripts_installed",
    "postgis_svn_version",
    "postgis_transform_geometry",
    "postgis_transform_pipeline_geometry",
    "postgis_type_name",
    "postgis_typmod_dims",
    "postgis_typmod_srid",
    "postgis_typmod_type",
}
"""Installed in the test database (PostGIS 3.7) with a name the generator would keep, but in no snapshot."""


@dataclass(frozen=True, slots=True)
class Installed:
    args: tuple[str, ...]
    ret: str
    defaults: int

    def shapes(self) -> Iterator[tuple[str, ...]]:
        """Argument types of every call it accepts: trailing arguments with defaults may be left out."""
        for k in range(self.defaults + 1):
            yield self.args[: len(self.args) - k]


@pytest.fixture(scope="module")
def setup_database(setup_database):
    for name in EXTENSIONS[1:]:
        setup_database.execute(pg.extension(name))
    yield setup_database


@pytest.fixture(scope="module")
def database_models():
    yield []


@pytest.fixture(scope="module")
def snapshot() -> Snapshot:
    snap = Snapshot.load(snapshot_path())
    assert snap.postgis_version == catalog.POSTGIS_VERSION
    return snap


@pytest.fixture
def installed(postgres: pw.PostgresqlDatabase) -> dict[str, list[Installed]]:
    """Functions of the PostGIS extensions by lower-cased name."""
    rows = postgres.execute_sql(
        """
        SELECT p.proname,
               array(SELECT format_type(t, NULL) FROM unnest(p.proargtypes::oid[]) AS t),
               format_type(p.prorettype, NULL),
               p.pronargdefaults
        FROM pg_proc p
        JOIN pg_depend d ON d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e'
        JOIN pg_extension e ON e.oid = d.refobjid
        WHERE e.extname = ANY(%s)
        """,
        (list(EXTENSIONS),),
    ).fetchall()
    out: dict[str, list[Installed]] = defaultdict(list)
    for name, args, ret, defaults in rows:
        out[name.lower()].append(Installed(tuple(args), ret, defaults))
    return out


def canonical(postgres: pw.PostgresqlDatabase, types: set[str]) -> dict[str, str]:
    """Manual spelling -> PostgreSQL's: ``float8`` and ``float`` are ``double precision``.

    Aggregates and window functions are written ``geometry set`` / ``geometry winset``
    (``setof raster`` once); multidimensional arrays are plain arrays to PostgreSQL.
    """
    plain = {t: typemap.base(t) for t in types}
    names = sorted({b for b, _ in plain.values()})
    rows = postgres.execute_sql(
        "SELECT t, format_type(to_regtype(t), NULL) FROM unnest(%s::text[]) AS t",
        (names,),
    ).fetchall()
    known = {t: c for t, c in rows if c is not None}
    return {t: f"{known.get(b, f'?{b}')}{'[]' if dims else ''}" for t, (b, dims) in plain.items()}


def current_functions(snapshot: Snapshot):
    """Functions of the current manual that are in the catalog."""
    names = {*catalog.NAMES.values(), *catalog.CG_NAMES.values()}
    return [without_topology(f) for f in snapshot.functions if f.name in names]


def test_every_function_is_installed(snapshot, installed):
    missing = [f.name for f in current_functions(snapshot) if f.name.lower() not in installed]
    assert missing == []


def test_every_typed_signature_is_callable(postgres, snapshot, installed):
    """The typing (api.pyi) comes from these signatures: each must match an installed overload."""
    functions = current_functions(snapshot)
    types = canonical(postgres, {a.type_ for f in functions for s in f.signatures for a in s.args})
    mismatches = []
    for f in functions:
        shapes = {shape for i in installed[f.name.lower()] for shape in i.shapes()}
        for sig in f.signatures:
            want = tuple(types[a.type_] for a in sig.args)
            if want not in shapes:
                mismatches.append(f"{f.name}({', '.join(want)})")
    assert mismatches == []


def test_results_are_converted_by_their_installed_type(installed):
    """``RETURNS`` picks the conversion (shapely, float, ...) by the category of the first argument."""
    wrong = []
    for name, by_first in catalog.RETURNS.items():
        overloads = installed.get(name.lower())
        if not overloads:
            continue  # not installed: test_every_function_is_installed reports current functions
        actual: dict[str, set[str]] = defaultdict(set)
        for i in overloads:
            actual[typemap.category(i.args[0]) if i.args else ""].add(typemap.category(i.ret))
        for first, category in by_first.items():
            # "other" means no conversion: always safe. Anything else must be the only result type.
            if category != "other" and actual.get(first) != {category}:
                wrong.append(f"{name}({first or '-'}): {category}, installed {sorted(actual.get(first, ()))}")
    assert wrong == []


def test_undocumented_functions(installed):
    """Installed functions no manual documents (since the oldest snapshot): known, and listed here.

    A new PostGIS may add some (or document them): update ``UNDOCUMENTED``, and scrape the
    manual if they are documented now.
    """
    snapshots = [snapshot_path(), *history.older_snapshots(snapshot_path())]
    documented = {f.name.lower() for p in snapshots for f in Snapshot.load(p).functions}
    undocumented = {name for name in installed if in_scope(name) and name not in documented}
    assert sorted(undocumented - UNDOCUMENTED) == [], "installed but in no manual: add to UNDOCUMENTED"
    assert sorted(UNDOCUMENTED - undocumented) == [], "documented or no longer installed: remove from UNDOCUMENTED"
