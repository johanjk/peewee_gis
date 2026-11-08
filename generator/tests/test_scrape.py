"""Parsing of manual pages, from an inline fixture (no network)."""

from bs4 import BeautifulSoup
from peewee_gis_generator import scrape

PAGE = """
<html><body>
<div class="refnamediv"><h2>Name</h2><p>ST_TileEnvelope — Creates a rectangular Polygon in Web Mercator (SRID:3857) using the XYZ tile system.</p></div>
<div class="refsynopsisdiv"><h2>Synopsis</h2>
<div class="funcsynopsis">
<p><code class="funcdef">geometry <strong class="fsfunc">ST_TileEnvelope</strong>(</code>integer <var class="pdparam">tileZoom</var>, integer <var class="pdparam">tileX</var>, integer <var class="pdparam">tileY</var>, geometry <var class="pdparam">bounds=SRID=3857;LINESTRING(-20037508.342789 -20037508.342789,20037508.342789 20037508.342789)</var>, float <var class="pdparam">margin=0.0</var><code>)</code>;</p>
</div>
<div class="funcsynopsis">
<p><code class="funcdef">double precision[] <b class="fsfunc">ST_Old</b>(</code>geometry set <var class="pdparam">geoms</var><code>)</code>;</p>
</div></div>
<div class="refsection"><h2>Description</h2>
<p>Creates a rectangular Polygon
   giving the extent of a tile.</p>
<p class="note">Availability: 3.0.0</p>
<p>Second paragraph.</p>
</div>
<div class="refsection"><h2>See Also</h2><p><a class="xref" href="ST_AsMVTGeom.html" title="ST_AsMVTGeom">ST_AsMVTGeom</a></p></div>
</body></html>
"""


def soup():
    return BeautifulSoup(PAGE, "lxml")


def test_signatures():
    first, second = scrape.signatures(soup())
    assert first.ret == "geometry"
    assert [(a.name, a.type_, a.default) for a in first.args] == [
        ("tileZoom", "integer", None),
        ("tileX", "integer", None),
        ("tileY", "integer", None),
        (
            "bounds",
            "geometry",
            "SRID=3857;LINESTRING(-20037508.342789 -20037508.342789,20037508.342789 20037508.342789)",
        ),
        ("margin", "float", "0.0"),
    ]
    # older manuals use <b class="fsfunc">; overloads may be in separate divs
    assert second.ret == "double precision[]"
    assert [(a.name, a.type_) for a in second.args] == [("geoms", "geometry set")]


def test_docs():
    s = soup()
    sections = scrape._refsections(s)
    assert scrape.summary(s) == "Creates a rectangular Polygon in Web Mercator (SRID:3857) using the XYZ tile system."
    assert (
        scrape.description(sections["Description"])
        == "Creates a rectangular Polygon\ngiving the extent of a tile.\n\nSecond paragraph."
    )
    (also,) = scrape.see_also(sections["See Also"], "https://postgis.net/docs/manual-3.6/")
    assert also.url == "https://postgis.net/docs/manual-3.6/ST_AsMVTGeom.html"


def test_normalise_type():
    assert scrape.normalise_type(" Double\u00a0Precision [ ] ") == "double precision[]"
    assert scrape.normalise_type("(1) raster") == "raster"
    assert scrape.normalise_type("VARIADIC integer") == "integer"


def test_scope():
    assert scrape.in_scope("ST_Area")
    assert scrape.in_scope("CG_3DArea")
    assert scrape.in_scope("Box2D")
    assert scrape.in_scope("postgis_srs")
    assert not scrape.in_scope("AddTopoGeometryColumn")
    assert not scrape.in_scope("Geocode")
    assert not scrape.in_scope('ST_X"]; import os  #')  # only plain identifiers reach the catalog
