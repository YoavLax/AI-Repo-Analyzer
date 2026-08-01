"""Environment-driven server settings (plan-v3-codecompass.md §3)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_TRUTHY = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True)
class Settings:
    allow_local_paths: bool
    local_repos_root: Path | None
    static_dir: Path | None
    max_concurrent_analyses: int

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ) if env is None else env
        allow_local = env.get("ALLOW_LOCAL_PATHS", "").strip().lower() in _TRUTHY
        root_raw = env.get("LOCAL_REPOS_ROOT", "").strip()
        static_raw = env.get("STATIC_DIR", "").strip()
        try:
            max_concurrent = max(1, int(env.get("MAX_CONCURRENT_ANALYSES", "4")))
        except ValueError:
            max_concurrent = 4
        return cls(
            allow_local_paths=allow_local,
            local_repos_root=Path(root_raw).resolve() if root_raw else None,
            static_dir=Path(static_raw).resolve() if static_raw else None,
            max_concurrent_analyses=max_concurrent,
        )
