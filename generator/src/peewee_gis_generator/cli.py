"""``peewee-gis-generator`` command line."""

from pathlib import Path  # ruff: ignore[TC003] - typer reads the annotations at runtime
from typing import Annotated

import typer

from .build import POSTGIS_VERSION, SNAPSHOTS, snapshot_path

app = typer.Typer(pretty_exceptions_enable=False, no_args_is_help=True)


@app.command()
def scrape(
    postgis_version: Annotated[str, typer.Argument(help="PostGIS manual version")] = POSTGIS_VERSION,
    output: Annotated[
        Path | None,
        typer.Option("-o", help="Snapshot file (default: snapshots/postgis-<v>.json)"),
    ] = None,
    cache: Annotated[Path | None, typer.Option(help="requests-cache sqlite file, avoids re-downloading")] = None,
    offline: Annotated[bool, typer.Option(help="Only use --cache, never hit the network")] = False,
) -> None:
    """Scrape the PostGIS manual into a JSON snapshot."""
    from .scrape import scrape as run  # ruff: ignore[PLC0415]

    out = output or SNAPSHOTS / f"postgis-{postgis_version}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with typer.progressbar(length=0, label="scraping") as bar:
        snap = run(postgis_version, cache=cache, offline=offline, progress=lambda _: bar.update(1))
    snap.dump(out)
    typer.echo(f"{len(snap.functions)} functions -> {out}")


@app.command()
def render(
    output_dir: Path,
    only: Annotated[
        str | None,
        typer.Option(help="'runtime' (catalog.py, for peewee_gis) or 'stubs' (api.pyi, for peewee_gis-stubs)"),
    ] = None,
    snapshot: Annotated[
        Path | None,
        typer.Option(help=f"Snapshot file (default: snapshots/postgis-{POSTGIS_VERSION}.json)"),
    ] = None,
) -> None:
    """Render python modules from a snapshot."""
    snapshot = snapshot or snapshot_path()
    from .render import ALL_FILES, RUNTIME_FILES, STUB_FILES, render_snapshot  # ruff: ignore[PLC0415]

    files = {"runtime": RUNTIME_FILES, "stubs": STUB_FILES, None: ALL_FILES}.get(only)
    if files is None:
        msg = f"--only must be 'runtime' or 'stubs', not {only!r}"
        raise typer.BadParameter(msg)
    render_snapshot(snapshot, output_dir, files=files)
    typer.echo(f"rendered {snapshot.name} -> {output_dir}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
