"""Scrape the PostGIS manual into a :class:`~peewee_gis_generator.model.Snapshot`."""

import re
import warnings
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from itertools import zip_longest
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString, Tag, XMLParsedAsHTMLWarning

from .model import Argument, Example, Function, SeeAlso, Signature, Snapshot

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    import requests

BASE = "https://postgis.net/docs/manual-{version}/"
INDEX = BASE + "PostGIS_Special_Functions_Index.html"

NBSP = "\u00a0"
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def session(cache: Path | None = None, *, offline: bool = False) -> requests.Session:
    """HTTP session, optionally backed by a requests-cache sqlite file."""
    if cache is None:
        import requests  # ruff: ignore[PLC0415]

        return requests.Session()

    import requests_cache  # ruff: ignore[PLC0415]

    return requests_cache.CachedSession(
        str(cache),
        backend="sqlite",
        expire_after=requests_cache.NEVER_EXPIRE,
        allowable_codes=(200, 404),
        filter_fn=_cacheable,
        only_if_cached=offline,
    )


def _cacheable(response: requests.Response) -> bool:
    """Pages, and the 404 of a reference chapter older manuals lack (offline scrapes skip it too).

    Any other 404 may be a glitch of the site: never cached, so the next scrape retries it.
    """
    return response.status_code == HTTPStatus.OK or (response.url or "").rsplit("/", 1)[-1] in REFERENCE_PAGES


def _get(http: requests.Session, url: str) -> BeautifulSoup:
    resp = http.get(url, timeout=60)
    resp.raise_for_status()
    # NOTE: resp.encoding reports ISO-8859-1 even though the pages are utf-8
    with warnings.catch_warnings():
        # newer manuals are served as XHTML; the HTML parser handles them fine
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        return BeautifulSoup(resp.content, features="lxml")


def _text(x: Tag | NavigableString | str) -> str:
    s = x if isinstance(x, str) else x.get_text()
    return s.replace(NBSP, " ").replace("\t", "    ")


def _squash(s: str) -> str:
    return " ".join(s.split())


REFERENCE_PAGES = ("reference.html", "reference_sfcgal.html", "RT_reference.html")
"""Reference chapters; each lists all of its function pages. ``reference_sfcgal`` is 3.5+."""


def _name(text: str) -> str:
    # "ST_MapAlgebra (expression version)": variants documented on their own page
    return re.sub(r"\s*\([^)]*\)$", "", _squash(text))


def _matrix(soup: BeautifulSoup, base: str) -> Iterator[tuple[str, str]]:
    """Rows of the function matrix of ``PostGIS_Special_Functions_Index``."""
    # older manuals: <table class="informaltable">, newer: first table with a <col class="function">
    col = soup.find("col", attrs={"class": "function"})
    table = col.find_parent("table") if isinstance(col, Tag) else soup.find("table", attrs={"class": "informaltable"})
    if not isinstance(table, Tag) or not isinstance(body := table.find("tbody") or table, Tag):
        msg = "function matrix table not found"
        raise ValueError(msg)  # ruff: ignore[TRY004]
    for row in body.find_all("tr"):
        cell = row.find("td")
        link = cell.find("a") if isinstance(cell, Tag) else None
        if isinstance(cell, Tag) and isinstance(link, Tag):
            yield _name(_text(cell)), urljoin(base, str(link["href"]))


def _reference(soup: BeautifulSoup, base: str) -> Iterator[tuple[str, str]]:
    """Function pages listed in a reference chapter's table of contents."""
    for a in soup.select("span.refentrytitle a[href]"):
        href = str(a["href"]).split("#", 1)[0]
        if href:
            yield _name(_text(a)), urljoin(base, href)


def function_index(http: requests.Session, version: str) -> Iterator[tuple[str, str]]:
    """``(name, url)`` of every documented function.

    From the reference chapters, which list every function page, and the function matrix
    of the special functions index (it misses e.g. the ``PostGIS_*_Version`` functions,
    and older manuals list no raster functions there).
    """
    import requests  # ruff: ignore[PLC0415] - only needed when scraping

    base = BASE.format(version=version)
    pages = [_matrix(_get(http, INDEX.format(version=version)), base)]
    for name in REFERENCE_PAGES:
        try:
            pages.append(_reference(_get(http, base + name), base))
        except requests.HTTPError as err:
            if err.response is None or err.response.status_code != HTTPStatus.NOT_FOUND:  # not in older manuals
                raise
    seen: set[tuple[str, str]] = set()
    for item in (i for page in pages for i in page):
        if item not in seen:
            seen.add(item)
            yield item


def in_scope(name: str) -> bool:
    """Functions exposed through ``peewee_gis.st``.

    Core, raster and SFCGAL functions live in the extension's schema (usually
    ``public``). Topology and tiger geocoder functions live in their own schemas
    and are left out.
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return False
    lower = name.lower()
    return lower.startswith(("st_", "cg_", "postgis_")) or lower in {"box2d", "box3d", "geometrytype"}


def normalise_type(t: str) -> str:
    """Normalise a type as written in a synopsis, e.g. ``'Geometry '`` -> ``'geometry'``."""
    t = _squash(t.replace(NBSP, " ")).lower()
    t = t.removeprefix("variadic ").strip()
    t = re.sub(r"^\(\d+\)\s*", "", t)  # numbered variants: "(1) raster"
    return re.sub(r"\s*\[\s*\]", "[]", t)


def signatures(soup: BeautifulSoup) -> Iterator[Signature]:
    """Parse ``div.funcsynopsis``.

    Each ``<p>`` is one overload::

        <code class="funcdef">geometry <strong class="fsfunc">ST_X</strong>(</code>
        integer <var class="pdparam">z</var>, float <var class="pdparam">margin=0.0</var><code>)</code>;
    """
    # one div per overload on some pages, all overloads in one div on others
    paragraphs = [p for div in soup.find_all("div", attrs={"class": "funcsynopsis"}) for p in div.find_all("p")]
    for p in paragraphs:
        funcdef = p.find("code", attrs={"class": "funcdef"})
        if not isinstance(funcdef, Tag):
            continue
        fsfunc = funcdef.find(attrs={"class": "fsfunc"})
        ret = "".join(_text(s) for s in funcdef.find_all(string=True) if s.parent is funcdef)
        ret = normalise_type(ret.removesuffix("(").replace("(", ""))
        if isinstance(fsfunc, Tag):
            ret = normalise_type(_text(funcdef).split(_text(fsfunc))[0])

        args: list[Argument] = []
        pending = ""
        for node in funcdef.next_siblings:
            if isinstance(node, NavigableString):
                pending += _text(node)
            elif isinstance(node, Tag) and "pdparam" in (node.get("class") or []):
                raw = _squash(_text(node))
                type_text = pending.rsplit(",", 1)[-1]
                pending = ""
                mode, _, rest = raw.partition(" ")
                if mode.upper() == "OUT":  # a column of the result (setof record), not an argument
                    continue
                if mode.upper() == "INOUT":
                    raw = rest
                name, _, default = raw.partition("=")
                variadic = "variadic" in type_text.lower()
                args.append(
                    Argument(
                        name=name.strip().replace(" ", "_"),
                        type_=normalise_type(type_text),
                        default=default.strip() or None,
                        variadic=variadic,
                    ),
                )
            elif isinstance(node, Tag):
                pending += _text(node)
        yield Signature(args=args, ret=ret)


def _refsections(soup: BeautifulSoup) -> dict[str, Tag]:
    out: dict[str, Tag] = {}
    for div in soup.find_all("div", attrs={"class": "refsection"}):
        h2 = div.find("h2")
        if isinstance(h2, Tag):
            out.setdefault(_squash(_text(h2)), div)
    return out


def summary(soup: BeautifulSoup) -> str | None:
    div = soup.find("div", attrs={"class": "refnamediv"})
    p = div.find("p") if isinstance(div, Tag) else None
    if not isinstance(p, Tag):
        return None
    _, _, s = _squash(_text(p)).partition("—")
    return s.strip() or None


def description(section: Tag | None) -> str | None:
    if section is None:
        return None
    # paragraphs with a class are version/notes boxes ("Enhanced: 3.1.0 ...")
    paras = [p for p in section.find_all("p", recursive=False) if not p.get("class")]
    texts = ["\n".join(line.strip() for line in _text(p).splitlines() if line.strip()) for p in paras]
    return "\n\n".join(t for t in texts if t) or None


_DEPRECATED = re.compile(
    r"^(?P<name>\w+) (?:is|has been) deprecated"
    r"(?: as of (?P<version>\d+(?:\.\d+)*))?\.?\s*(?P<rest>.*)$",
)


def deprecation(soup: BeautifulSoup, name: str) -> str | None:
    """Deprecation notice from the page's warning/note boxes, if it deprecates ``name`` itself.

    The manual writes ``ST_MapAlgebraExpr is deprecated as of 2.1.0. Use ST_MapAlgebra
    (expression version) instead.`` Notes about *other* deprecated functions ("Use of
    Variant 1 is discouraged since ST_MapAlgebraFctNgb has been deprecated") don't count.
    """
    for box in soup.find_all("div", attrs={"class": ["warning", "note", "caution", "important"]}):
        for p in box.find_all("p"):
            m = _DEPRECATED.match(_squash(_text(p)))
            if m is None or m["name"].lower() != name.lower():
                continue
            since = f" since PostGIS {m['version']}" if m["version"] else ""
            rest = m["rest"].strip()
            return f"Deprecated{since}." + (f" {rest}" if rest else "")
    return None


def see_also(section: Tag | None, base: str) -> list[SeeAlso]:
    if section is None:
        return []
    return [
        SeeAlso(title=_squash(str(a.get("title") or _text(a))), url=urljoin(base, str(a["href"])))
        for a in section.find_all("a", attrs={"class": "xref"})
    ]


def examples(sections: dict[str, Tag]) -> list[Example]:
    out: list[Example] = []
    for title, section in sections.items():
        if not title.startswith("Example"):
            continue
        descs = section.find_all("p")
        codes = section.find_all("pre", attrs={"class": "programlisting"})
        out.extend(
            Example(
                desc=_squash(_text(d)) if d is not None else None,
                code=_text(c).strip() if c is not None else None,
            )
            for d, c in zip_longest(descs, codes)
        )
    return out


def page(http: requests.Session, version: str, name: str, url: str) -> Function:
    try:
        soup = _get(http, url)
        sections = _refsections(soup)
        base = BASE.format(version=version)
        return Function(
            name=name,
            url=url,
            summary=summary(soup),
            description=description(sections.get("Description")),
            signatures=list(signatures(soup)),
            see_also=see_also(sections.get("See Also"), base),
            examples=examples(sections),
            deprecated=deprecation(soup, name),
        )
    except Exception as err:
        msg = f"could not parse {name} ({url})"
        raise ValueError(msg) from err


def merge(pages: list[Function]) -> Function:
    """Merge pages documenting the same SQL name (e.g. geometry and raster variants).

    The page named ``<name>.html`` is primary (its docs win); signatures and see-also
    links are concatenated.
    """
    pages = sorted(pages, key=lambda p: (not p.url.endswith(f"/{p.name}.html"), p.url))
    first = pages[0]
    sigs = [s for p in pages for s in p.signatures]
    seen: set[str] = set()
    also = [a for p in pages for a in p.see_also if not (a.url in seen or seen.add(a.url))]
    return Function(
        name=first.name,
        url=first.url,
        summary=first.summary,
        description=first.description,
        signatures=list({repr(x): x for x in sigs}.values()),
        see_also=also,
        examples=first.examples,
        other_urls=[p.url for p in pages[1:]],
        deprecated=next((p.deprecated for p in pages if p.deprecated), None),
    )


def scrape(
    version: str,
    *,
    cache: Path | None = None,
    offline: bool = False,
    workers: int = 8,
    progress: Callable[[str], None] | None = None,
) -> Snapshot:
    """Scrape all in-scope functions (see :func:`in_scope`) of one manual version."""
    http = session(cache, offline=offline)
    index = [(n, u) for n, u in function_index(http, version) if IDENT.match(n) and in_scope(n)]

    def one(item: tuple[str, str]) -> Function:
        f = page(http, version, *item)
        if progress is not None:
            progress(f.name)
        return f

    # sqlite-backed caches don't like concurrent writers; only parallelise plain sessions
    n = workers if cache is None else 1
    with ThreadPoolExecutor(max_workers=n) as pool:
        pages = list(pool.map(one, index))

    by_name: dict[str, list[Function]] = {}
    for p in pages:
        by_name.setdefault(p.name, []).append(p)
    # kept without signatures too (rendering skips them): history needs every documented name
    funcs = [merge(ps) for ps in by_name.values()]
    funcs.sort(key=lambda f: f.name.lower())
    return Snapshot(postgis_version=version, functions=funcs)
