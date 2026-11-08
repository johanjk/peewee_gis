r"""Corrections to signatures as written in the manual.

The synopsis doesn't always show the SQL defaults; without them the stubs would
demand arguments PostgreSQL doesn't. Keep entries checked against
``\df+ <function>`` in a PostGIS database.
"""

from dataclasses import replace

from ..model import Function, Signature

# function -> argument name -> SQL default
DEFAULTS: dict[str, dict[str, str]] = {
    # ST_CurveToLine(geom geometry, tol double precision DEFAULT 32, toltype integer DEFAULT 0, flags integer DEFAULT 0)
    "ST_CurveToLine": {"tolerance": "32", "tolerance_type": "0", "flags": "0"},
}


def correct(f: Function) -> Function:
    defaults = DEFAULTS.get(f.name)
    if not defaults:
        return f
    sigs = [
        Signature(args=[replace(a, default=defaults.get(a.name, a.default)) for a in s.args], ret=s.ret)
        for s in f.signatures
    ]
    return replace(f, signatures=sigs)
