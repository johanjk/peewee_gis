"""Functions dropped from the manual: kept, marked deprecated with what the manuals say."""

from peewee_gis_generator.build import digest
from peewee_gis_generator.model import Argument, Function, Signature, Snapshot
from peewee_gis_generator.render import history, render_function, render_snapshot, select

SIG = Signature(args=[Argument("g", "geometry")], ret="geometry")


def fn(name: str, deprecated: str | None = None) -> Function:
    return Function(name=name, url=f"u/{name}", summary="S.", description=None, signatures=[SIG], deprecated=deprecated)


def snap(version: str, *functions: Function) -> Snapshot:
    return Snapshot(postgis_version=version, functions=list(functions))


def test_removed_keeps_the_newest_documentation():
    old = fn("ST_Old", deprecated="Deprecated since PostGIS 3.5.0. Use CG_Old instead.")
    gone = history.removed(
        snap("3.7", fn("ST_Area")),
        [snap("3.6", fn("ST_Area"), old), snap("3.5", fn("ST_Area"), fn("ST_Old"))],
    )
    assert [(f.name, f.deprecated) for f in gone] == [
        (
            "ST_Old",
            "Not in the PostGIS 3.7 manual (last documented in 3.6). Deprecated since 3.5.0: use CG_Old instead.",
        ),
    ]


def test_removed_without_a_notice():
    (f,) = history.removed(snap("3.4", fn("ST_Area")), [snap("3.2", fn("ST_Gone")), snap("3.3", fn("ST_Area"))])
    assert f.deprecated == "Not in the PostGIS 3.4 manual (last documented in 3.2)."


def test_only_the_spelling_changed():
    (f,) = history.removed(snap("3.7", fn("ST_ZMFlag")), [snap("3.6", fn("ST_Zmflag"))])
    assert f.deprecated == "Spelled ST_ZMFlag since PostGIS 3.7: use st.ZMFlag."


def test_spelling_changed_before_the_current_version():
    (f,) = history.removed(
        snap("3.7", fn("ST_ZMFlag")),
        [snap("3.4", fn("ST_Zmflag")), snap("3.5", fn("ST_ZMFlag")), snap("3.6", fn("ST_ZMFlag"))],
    )
    assert f.deprecated == "Spelled ST_ZMFlag since PostGIS 3.5: use st.ZMFlag."


def test_spelling_changed_twice():
    (f, g) = history.removed(
        snap("3.7", fn("ST_ZMFlag")),
        [snap("3.4", fn("ST_Zmflag")), snap("3.5", fn("ST_ZMflag")), snap("3.6", fn("ST_ZMflag"))],
    )
    assert (f.name, g.name) == ("ST_Zmflag", "ST_ZMflag")
    assert f.deprecated == g.deprecated == "Spelled ST_ZMFlag since PostGIS 3.7: use st.ZMFlag."


def test_spelling_changed_on_cg():
    (f,) = history.removed(snap("3.7", fn("CG_3DArea")), [snap("3.6", fn("CG_3darea"))])
    assert f.deprecated == "Spelled CG_3DArea since PostGIS 3.7: use cg.n3DArea."
    assert render_function(f).deprecated == f.deprecated  # names the attribute already: no (cg.n3DArea) hint


def test_a_leading_name_keeps_its_case():
    old = fn("ST_Old", deprecated="Deprecated since PostGIS 3.5.0. ST_New replaces it.")
    (f,) = history.removed(snap("3.7"), [snap("3.6", old)])
    assert f.deprecated.endswith("Deprecated since 3.5.0: ST_New replaces it.")


def test_a_function_without_signatures_is_not_removed():
    undocumented = Function(name="ST_Old", url="u", summary=None, description=None, signatures=[])
    assert history.removed(snap("3.7", undocumented), [snap("3.6", fn("ST_Old"))]) == []


def test_spelling_only_points_to_rendered_functions():
    page = Function(name="box2d", url="u", summary=None, description=None, signatures=[])
    (f,) = history.removed(snap("3.7", page), [snap("3.6", fn("BOX2D"))])
    assert f.deprecated == "Not in the PostGIS 3.7 manual (last documented in 3.6)."


def test_current_attributes_win():
    current = select([fn("ST_Area")])
    # an older function rendering to an attribute the current version uses is left out
    assert select([fn("ST_Area", deprecated="x")], taken=current) == []
    assert [r.attr for r in select([fn("ST_Old", deprecated="x")], taken=current)] == ["Old"]
    assert render_function(fn("ST_Old", deprecated="x")).deprecated == "x"


def test_older_snapshots(tmp_path):
    for v in ("3.10", "3.2", "3.9", "3.11"):
        snap(v).dump(tmp_path / f"postgis-{v}.json")
    (tmp_path / "notes.json").write_text("{}")
    older = history.older_snapshots(tmp_path / "postgis-3.10.json")
    assert [p.name for p in older] == ["postgis-3.2.json", "postgis-3.9.json"]  # numeric order, older only


def test_render_snapshot_uses_older_snapshots(tmp_path):
    snap("3.6", fn("ST_Area"), fn("ST_Old", deprecated="Deprecated since PostGIS 3.5.0. Use CG_Old instead.")).dump(
        tmp_path / "postgis-3.6.json",
    )
    snap("3.7", fn("ST_Area")).dump(tmp_path / "postgis-3.7.json")
    out = tmp_path / "out"
    render_snapshot(tmp_path / "postgis-3.7.json", out)
    api = (out / "api.pyi").read_text()
    assert "@deprecated(" in api
    assert "Not in the PostGIS 3.7 manual (last documented in 3.6). Deprecated since 3.5.0: use CG_Old (cg.Old)" in api
    assert "since PostGIS 3.6 but no longer in this manual" in api
    assert '"Old": "ST_Old"' in (out / "catalog.py").read_text()  # still callable, with its result conversion
    render_snapshot(tmp_path / "postgis-3.7.json", out, older=[])
    assert "ST_Old" not in (out / "api.pyi").read_text()


def test_digest_reads_the_older_snapshots_only(tmp_path):
    for v in ("3.6", "3.7", "3.8"):
        snap(v).dump(tmp_path / f"postgis-{v}.json")
    current = tmp_path / "postgis-3.7.json"
    key = digest(current, ("api.pyi",))
    snap("3.8", fn("ST_New")).dump(tmp_path / "postgis-3.8.json")
    assert digest(current, ("api.pyi",)) == key  # a newer snapshot isn't rendered from
    snap("3.6", fn("ST_Old")).dump(tmp_path / "postgis-3.6.json")
    assert digest(current, ("api.pyi",)) != key
