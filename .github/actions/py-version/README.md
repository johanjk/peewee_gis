# Python version matrix from `pyproject.toml`

Parse a package's `project.requires-python` field
from `pyproject.toml` and returns a JSON array of compatible, stable CPython
major/minor versions. The list is based on the CPython versions currently
available through `uv`.

For example, `>=3.10,<3.13` includes available versions from Python 3.10 through
3.12. Patch releases are not included.

## Example

```yaml

jobs:
  generate-matrix:
    runs-on: ubuntu-latest
    outputs:
      matrix: ${{ steps.set-matrix.outputs.matrix }}
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false

      - name: Set Python matrix
        id: set-matrix
        uses: ./.github/actions/py-version
        with:
          pkg-dir: ./backend

  testing:
    needs: generate-matrix
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python: ${{ fromJson(needs.generate-matrix.outputs.matrix) }}

    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false

      - name: Setup python version ${{ matrix.python }}
        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: ${{ matrix.python }}
```
