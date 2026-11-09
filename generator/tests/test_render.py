"""Rendering from the committed snapshot."""

import ast
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest
from peewee_gis_generator import build
from peewee_gis_generator.model import Argument, Function, Signature, Snapshot
from peewee_gis_generator.render import render_function, render_snapshot, select, source, typemap

SNAPSHOT = build.snapshot_path()  # the version the packages build from


@pytest.fixture(scope="module")
def snapshot():
    return Snapshot.load(SNAPSHOT)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    out = tmp_path_factory.mktemp("generated")
    render_snapshot(SNAPSHOT, out)
    return out


def test_snapshot_roundtrip(snapshot, tmp_path):
    snapshot.dump(tmp_path / "s.json")
    assert Snapshot.load(tmp_path / "s.json") == snapshot


def test_typemap():
    assert typemap.marker("double precision") == "float"
    assert typemap.marker("setof geometry") == "geometry"
    assert typemap.marker("geometry set") == "geometry"
    assert typemap.marker("integer[][]") == "list[list[int]]"
    assert typemap.marker("geometry_dump[]") == "list[record]"
    assert typemap.marker("(geometry, double precision)") == "record"
    assert typemap.marker("void") == "None"
    assert typemap.argument("geometry") == "Arg[Geom]"
    assert typemap.argument("text[]") == "Arg[Sequence[str]]"
    assert typemap.argument("box2d") == "Arg[None]"
    assert typemap.category("geography") == "geography"
    assert typemap.category("setof geometry") == "geometry"
    assert typemap.category("geometry[]") == "other"


def test_names():
    assert typemap.py_name("ST_Area") == "Area"
    assert typemap.py_name("ST_3DDistance") == "n3DDistance"
    assert typemap.py_name("Box2D") == "Box2D"
    assert typemap.py_name("CG_3DArea") == "CG_3DArea"


def test_render_function():
    f = Function(
        name="ST_Area",
        url="https://postgis.net/docs/manual-3.6/ST_Area.html",
        summary="Returns the area.",
        description='Has "quotes" and a \\ backslash.',
        signatures=[
            Signature(args=[Argument("g1", "geometry")], ret="float"),
            Signature(args=[Argument("geog", "geography"), Argument("use_spheroid", "boolean", "true")], ret="float"),
        ],
    )
    r = render_function(f)
    assert r.attr == "Area"
    assert r.returns == {"geometry": "other", "geography": "other"}
    assert r.chain[0].startswith("    @overload\n    def Area(self: ChainMethods[geometry]) -> StChain[float]:")
    assert "def Area(self: ChainMethods[geography], use_spheroid: Arg[bool] = ...) -> StChain[float]:" in r.chain[1]
    assert "def Area(self, g1: Arg[Geom], /) -> StChain[float]:" in r.root[0]
    assert "\\\\ backslash" in r.root[0]


def test_select_has_no_collisions(snapshot):
    funcs = select(snapshot.functions)
    names = [f.attr for f in funcs]
    assert len(names) == len(set(names))
    assert {"Area", "Transform", "AsMVT", "AsMVTGeom", "TileEnvelope", "n3DDistance", "Box2D"} <= set(names)
    assert "AddEdgeModFace" not in names  # topology schema


def test_outputs_are_valid_python(rendered):
    for name in ("catalog.py", "api.pyi", "__init__.py"):
        ast.parse((rendered / name).read_text(), filename=name)


def test_catalog_imports(rendered):
    spec = importlib.util.spec_from_file_location("catalog", rendered / "catalog.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.NAMES["Transform"] == "ST_Transform"
    assert mod.RETURNS["ST_Transform"]["geometry"] == "geometry"
    assert mod.RETURNS["ST_Transform"]["raster"] == "raster"
    assert "ST_Area" not in mod.RETURNS  # "other" only


def test_builtin_names_get_an_underscore():
    f = Function(
        name="ST_AsText",
        url="u",
        summary="s",
        description=None,
        signatures=[Signature(args=[Argument("g", "geometry"), Argument("format", "text", "'x'")], ret="text")],
    )
    assert "format_: Arg[str] = ..." in render_function(f).chain[0]


def test_docstring_layout():
    long = "ST_X: " + "word " * 40
    doc = source.docstring(long, ["See: u"]).splitlines()
    assert doc[0] == '        """ST_X.'
    assert not doc[1]
    assert all(len(line) <= source.LINE_LENGTH for line in doc)
    assert source.docstring("ST_X: no stop", []) == '        """ST_X: no stop.\n        """'
    assert source.docstring("Fine!", []).startswith('        """Fine!')


def test_deprecated_overloads():
    """Every overload of a deprecated function gets @deprecated, below @overload."""
    sigs = [
        Signature(args=[Argument("g", "geometry")], ret="geometry"),
        Signature(args=[Argument("g", "geometry"), Argument("n", "integer")], ret="geometry"),
    ]
    f = Function(name="ST_Old", url="u", summary="Old.", description=None, signatures=sigs, deprecated="Use ST_New.")
    r = render_function(f)
    for block in (*r.root, *r.chain):
        assert block.startswith('    @overload\n    @deprecated("Use ST_New.")\n    def Old(')
        assert "Use ST_New." in block.split('"""')[1]  # and in the docstring
    plain = render_function(Function(name="ST_X", url="u", summary=None, description=None, signatures=sigs[:1]))
    assert "@deprecated" not in plain.root[0]


def test_deprecated_functions_in_the_snapshot(snapshot, rendered):
    deprecated = {f.name for f in snapshot.functions if f.deprecated}
    assert {"ST_MapAlgebraExpr", "ST_MapAlgebraFct", "ST_MapAlgebraFctNgb"} <= deprecated
    assert "ST_MapAlgebra" not in deprecated
    # listed in the index as "ST_MapAlgebra (expression version)" etc.: merged into one function
    assert any(f.name == "ST_MapAlgebra" and f.other_urls for f in snapshot.functions)
    assert "from warnings import deprecated" in (rendered / "api.pyi").read_text()


def test_select_rejects_names_that_are_not_identifiers():
    """catalog.py is imported at runtime: a scraped name must not be able to inject code."""
    sig = Signature(args=[Argument("g", "geometry")], ret="double precision")
    bad = Function(name='ST_X": __import__("os"), "y', url="u", summary=None, description=None, signatures=[sig])
    with pytest.raises(ValueError, match="not a plain SQL identifier"):
        select([bad])


def test_signature_layout():
    assert source.signature("F", ["self"], "R") == "    def F(self) -> R:"
    long = source.signature("F", ["self", *(f"a{i}: Arg[float] = ..." for i in range(9))], "StChain[float]")
    lines = long.splitlines()
    assert lines[0] == "    def F("
    assert lines[1] == "        self,"
    assert lines[-1] == "    ) -> StChain[float]:"


ROOT = Path(__file__).parents[2]


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff not installed")
def test_outputs_pass_ruff(rendered):
    """Same checks as `poe lint:generated`, on freshly rendered output."""
    config = ["--config", str(ROOT / "ruff.toml"), "--no-respect-gitignore"]
    ignore = ["--extend-ignore", "PYI021,N802,N803,RUF002"]  # as for st/_generated in ruff.toml
    check = subprocess.run(
        ["ruff", "check", *config, *ignore, str(rendered)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0, check.stdout
    fmt = subprocess.run(
        ["ruff", "format", "--check", *config, str(rendered)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert fmt.returncode == 0, fmt.stdout
