"""Parsing of manual pages, from an inline fixture (no network)."""

from io import BytesIO

from bs4 import BeautifulSoup
from peewee_gis_generator import scrape
from requests.adapters import HTTPAdapter
from urllib3 import HTTPResponse

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


WARNING = """
<html><body><div class="refentry"><div class="refsection"><h2>Description</h2>
<div class="warning"><table><tr><td><p>
<a class="xref" href="RT_ST_MapAlgebraExpr.html">ST_MapAlgebraExpr</a> is deprecated as of 2.1.0. Use
<a class="xref" href="RT_ST_MapAlgebra_expr.html">ST_MapAlgebra (expression version)</a> instead.
</p></td></tr></table></div>
<div class="warning"><table><tr><td><p>
Use of Variant 1 is discouraged since ST_MapAlgebraFctNgb has been deprecated as of 2.1.0.
</p></td></tr></table></div>
</div></div></body></html>
"""


def test_deprecation():
    page = BeautifulSoup(WARNING, "lxml")
    assert scrape.deprecation(page, "ST_MapAlgebraExpr") == (
        "Deprecated since PostGIS 2.1.0. Use ST_MapAlgebra (expression version) instead."
    )
    # a note about another deprecated function doesn't deprecate this one
    assert scrape.deprecation(page, "ST_Sum4ma") is None
    assert scrape.deprecation(soup(), "ST_TileEnvelope") is None


class _Manual(HTTPAdapter):
    """A manual with only ST_Area, without the SFCGAL chapter (as before PostGIS 3.5)."""

    def send(self, request, *_args, **_kwargs):
        raw = HTTPResponse(
            body=BytesIO(b'<table class="informaltable"><tr><td><a href="ST_Area.html">ST_Area</a></td></tr></table>'),
            headers={"Content-Type": "text/html"},
            status=404 if any(x in (request.url or "") for x in ("sfcgal", "Gone")) else 200,
            preload_content=False,
            request_url=request.url,
        )
        return self.build_response(request, raw)


def test_a_missing_chapter_is_cached_for_offline_scrapes(tmp_path):
    http = scrape.session(tmp_path / "c.sqlite")
    http.mount("https://", _Manual())
    expected = [("ST_Area", "https://postgis.net/docs/manual-3.4/ST_Area.html")]
    assert list(scrape.function_index(http, "3.4")) == expected
    offline = scrape.session(tmp_path / "c.sqlite", offline=True)
    assert list(scrape.function_index(offline, "3.4")) == expected  # the 404 came from the cache, not a 504


def test_other_404s_are_not_cached(tmp_path):
    """A page missing by a glitch of the site is retried by the next scrape."""
    url = "https://postgis.net/docs/manual-3.4/ST_Gone.html"
    http = scrape.session(tmp_path / "c.sqlite")
    http.mount("https://", _Manual())
    assert http.get(url).status_code == 404
    assert scrape.session(tmp_path / "c.sqlite", offline=True).get(url).status_code == 504  # not cached
