"""Make the recipe importable under any pytest invocation.

`python -m pytest` adds the current dir to sys.path, but a bare `pytest`
does not, so `import monitor` in tests/ would fail to collect. pytest always
imports this conftest before collecting tests, so inserting the recipe dir
here guarantees the import works either way.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
