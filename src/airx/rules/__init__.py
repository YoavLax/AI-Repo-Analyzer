"""Rule modules. Importing this package registers every built-in rule into
`airx.rules.registry`."""
from __future__ import annotations

from airx.rules import agents as _agents  # noqa: F401
from airx.rules import foundation as _foundation  # noqa: F401
from airx.rules import quality as _quality  # noqa: F401
from airx.rules import safety as _safety  # noqa: F401
from airx.rules import scoping as _scoping  # noqa: F401
from airx.rules import skills as _skills  # noqa: F401
from airx.rules import tooling as _tooling  # noqa: F401
from airx.rules import verification as _verification  # noqa: F401
