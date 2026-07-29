import sys
from pathlib import Path

# Make `src/` importable without requiring an editable install.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import airx.rules  # noqa: E402,F401  (registers all built-in rules once per session)
