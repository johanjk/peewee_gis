"""Render a snapshot into the ``peewee_gis.st._generated`` package.

Outputs:

``catalog.py``
    Runtime data: python attribute -> SQL name, and per function the conversion
    category of its result keyed by the category of its first argument.
``api.pyi``
    Typing only: ``StRoot`` (``st.X(geom, ...)``) and ``ChainMethods[T]``
    (``geom.st.X(...)``, first argument filled by the chain, overloads selected by
    the type ``T`` of the chained value). Docstrings come from the manual.
"""

import builtins
import json
import keyword
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import jinja2

from ..model import Function, Signature, Snapshot
from . import history, source, typemap
from .corrections import correct

if TYPE_CHECKING:
    from collections.abc import Iterable

TEMPLATES = Path(__file__).parent / "templates"
SKIP_LEGACY = {"GeometryType"}  # collides with ST_GeometryType -> st.GeometryType
TOPOLOGY_ARGS = {"atopology", "toponame", "topology_name", "topology"}


def is_topology(f: Function) -> bool:
    """ST_ functions of postgis_topology live in the ``topology`` schema; left out."""
    return all(s.args and s.args[0].name.lower() in TOPOLOGY_ARGS for s in f.signatures)


@dataclass(frozen=True, slots=True)
class Rendered:
    """One function, ready for the templates."""

    attr: str
    sql: str
    root: list[str]
    chain: list[str]
    returns: dict[str, str]
    deprecated: str | None = None


def _param_name(name: str, seen: set[str]) -> str:
    name = typemap.py_identifier(name.lower() if name.isupper() else name)
    if name in dir(builtins):  # `format`, `input`, ...; the runtime drops the `_` again
        name = f"{name}_"
    while name in seen or name == "self":
        name = f"{name}_"
    seen.add(name)
    return name


def _params(sig: Signature, *, skip_first: bool) -> list[str]:
    args = sig.args[1:] if skip_first else sig.args
    out: list[str] = []
    seen: set[str] = set()
    required = [a for a in args if a.default is None]
    # a required parameter after one with a default: the manual isn't a reliable
    # source of names then; make everything positional-only
    all_positional = any(a.default is not None for a in args[: len(required)])
    slash_after = -1
    for i, a in enumerate(args):
        if a.default is None:
            slash_after = i
    for i, a in enumerate(args):
        name = _param_name(a.name, seen)
        ann = typemap.argument(a.type_)
        if a.variadic:
            out.append(f"*{name}: {ann}")
            continue
        default = " = ..." if a.default is not None and not all_positional else ""
        out.append(f"{name}: {ann}{default}")
        if i == slash_after or (all_positional and i == len(args) - 1):
            out.append("/")
    return out


def _doc(f: Function) -> str:
    """Docstring from the manual: summary, description, links."""
    summary = f"{f.name}: {f.summary}" if f.summary else f.name
    body: list[str] = [*source.wrap(f.deprecated), ""] if f.deprecated else []
    description = f.description or ""
    paragraphs = description.split("\n\n")
    if f.summary and paragraphs and " ".join(paragraphs[0].split()) == " ".join(f.summary.split()):
        paragraphs = paragraphs[1:]  # the first paragraph often repeats the summary
    if text := "\n\n".join(paragraphs).strip():
        body.extend([*source.wrap(text), ""])
    body.extend(source.reference("See", f.url, source.BODY_INDENT))
    for url in f.other_urls:
        body.extend(source.reference("Also", url, source.BODY_INDENT))
    if f.see_also:
        body.append("See also:")
        for a in f.see_also:
            body.extend(f"    {line}" for line in source.reference(a.title, a.url, source.BODY_INDENT + "    "))
    return source.docstring(summary, body)


def _overloads(
    name: str,
    sigs: Iterable[tuple[list[str], str]],
    doc: str,
    deprecated: str | None = None,
) -> list[str]:
    """``def`` blocks, deduplicated, with the docstring on each overload.

    A deprecated function gets ``@deprecated`` (PEP 702) on every overload, below ``@overload``.
    """
    unique = list({(tuple(p), r): (p, r) for p, r in sigs}.values())
    deco = f"{source.METHOD_INDENT}@overload\n" if len(unique) > 1 else ""
    if deprecated is not None:
        deco += f"{source.METHOD_INDENT}@deprecated({_py_string(deprecated)})\n"
    return [f"{deco}{source.signature(name, params, ret)}\n{doc}" for params, ret in unique]


def _py_string(text: str) -> str:
    """A double-quoted python string literal (ruff's quote style)."""
    return json.dumps(text, ensure_ascii=False)


def render_function(f: Function) -> Rendered:
    attr = typemap.py_name(f.name)
    doc = _doc(f)

    root: list[tuple[list[str], str]] = []
    chain: list[tuple[list[str], str]] = []
    returns: dict[str, str] = {}
    for sig in f.signatures:
        ret = f"StChain[{typemap.marker(sig.ret)}]"
        root.append((["self", *_params(sig, skip_first=False)], ret))
        first = typemap.category(sig.args[0].type_) if sig.args else ""
        cat = typemap.category(sig.ret)
        # conflicting overloads (same first-argument category): don't convert
        returns[first] = cat if returns.get(first, cat) == cat else "other"
        if sig.args:
            this = typemap.marker(sig.args[0].type_)
            chain.append(([f"self: ChainMethods[{this}]", *_params(sig, skip_first=True)], ret))

    return Rendered(
        attr=attr,
        sql=f.name,
        root=_overloads(attr, root, doc, f.deprecated),
        chain=_overloads(attr, chain, doc, f.deprecated),
        returns=dict(returns),
        deprecated=f.deprecated,
    )


SQL_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def select(functions: Iterable[Function], taken: Iterable[Rendered] = ()) -> list[Rendered]:
    """Render ``functions``; with ``taken`` (removed functions), attributes already in use are skipped."""
    used = {r.attr for r in taken}
    out: dict[str, Rendered] = {}
    for f in functions:
        if f.name in SKIP_LEGACY or not f.signatures or is_topology(f):
            continue
        if not SQL_IDENT.match(f.name):  # the catalog is code: only plain identifiers get into it
            msg = f"{f.name!r} is not a plain SQL identifier"
            raise ValueError(msg)
        r = render_function(correct(f))
        if keyword.iskeyword(r.attr):
            msg = f"{f.name}: attribute {r.attr!r} is a keyword"
            raise ValueError(msg)
        if r.attr in used:
            continue
        if r.attr in out:
            msg = f"attribute {r.attr!r} for both {out[r.attr].sql} and {f.name}"
            raise ValueError(msg)
        out[r.attr] = r
    return sorted(out.values(), key=lambda r: r.attr.lower())


MARKERS = ("box2d", "box3d", "geography", "geometry", "json", "raster", "record", "spheroid")


def used_markers(funcs: Iterable[Rendered]) -> list[str]:
    """SQL type markers the signatures use; imported by ``api.pyi``."""
    text = "\n".join(line.split('"""')[0] for f in funcs for o in (*f.root, *f.chain) for line in o.splitlines())
    return [m for m in MARKERS if f"[{m}]" in text]  # type position: StChain[geometry], list[record]


RUNTIME_FILES = ("catalog.py", "__init__.py")
"""Shipped in peewee_gis: the function catalog."""
STUB_FILES = ("api.pyi",)
"""Shipped in peewee_gis-stubs: typing and docstrings."""
ALL_FILES = RUNTIME_FILES + STUB_FILES


def _load(path: Path) -> Snapshot:
    snap = Snapshot.load(path)
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", snap.postgis_version) or not re.fullmatch(r"[\w.-]+", path.name):
        msg = f"unexpected version {snap.postgis_version!r} or snapshot name {path.name!r}"
        raise ValueError(msg)
    return snap


def render_snapshot(
    snapshot: Path,
    output_dir: Path,
    files: Iterable[str] = ALL_FILES,
    older: Iterable[Path] | None = None,
) -> None:
    """Render ``files`` from ``snapshot``.

    ``older`` snapshots (default: the older ``postgis-*.json`` next to ``snapshot``) add
    the functions PostGIS has since removed, marked deprecated with how to update.
    """
    snap = _load(snapshot)
    past = [_load(p) for p in (history.older_snapshots(snapshot) if older is None else older)]
    current = select(snap.functions)
    gone = select(history.removed(snap, past), taken=current)
    funcs = sorted([*current, *gone], key=lambda r: r.attr.lower())
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES),
        keep_trailing_newline=True,
        autoescape=False,  # ruff: ignore[S701] - renders python source
    )
    ctx = {
        "version": snap.postgis_version,
        "oldest": min((s.postgis_version for s in past), key=history.version_key, default=None),
        "functions": funcs,
        "snapshot": snapshot.name,
        "markers": used_markers(funcs),
        "uses_deprecated": any(f.deprecated for f in funcs),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in files:
        text = env.get_template(f"{name}.jinja").render(ctx)
        tmp = output_dir / f".{name}.tmp"
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(output_dir / name)
