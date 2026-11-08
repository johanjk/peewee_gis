"""The python blocks of the README and docs run (no database: they only compile SQL)."""

from pathlib import Path

import pytest
from mktestdocs import check_md_file

ROOT = Path(__file__).parents[1]
FILES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_docs(path):
    check_md_file(path, memory=True)
