"""Environment-driven server settings (plan-v3-codecompass.md §3)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from airx.ingest import MAX_FETCH_FILES as DEFAULT_MAX_FETCH_FILES
from airx.ingest import MAX_FILE_BYTES as DEFAULT_MAX_FILE_BYTES
from airx.ingest import MAX_TOTAL_BYTES as DEFAULT_MAX_TOTAL_BYTES

_TRUTHY = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True)
class Settings:
    allow_local_paths: bool
    local_repos_root: Path | None
    static_dir: Path | None
    max_concurrent_analyses: int
    max_fetch_files: int
    max_file_bytes: int
    max_total_bytes: int

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
        try:
            max_fetch_files = max(1, int(env.get("MAX_FETCH_FILES", str(DEFAULT_MAX_FETCH_FILES))))
        except ValueError:
            max_fetch_files = DEFAULT_MAX_FETCH_FILES
        try:
            max_file_bytes = max(1024, int(env.get("MAX_FILE_BYTES", str(DEFAULT_MAX_FILE_BYTES))))
        except ValueError:
            max_file_bytes = DEFAULT_MAX_FILE_BYTES
        try:
            max_total_bytes = max(1024, int(env.get("MAX_TOTAL_BYTES", str(DEFAULT_MAX_TOTAL_BYTES))))
        except ValueError:
            max_total_bytes = DEFAULT_MAX_TOTAL_BYTES
        return cls(
            allow_local_paths=allow_local,
            local_repos_root=Path(root_raw).resolve() if root_raw else None,
            static_dir=Path(static_raw).resolve() if static_raw else None,
            max_concurrent_analyses=max_concurrent,
            max_fetch_files=max_fetch_files,
            max_file_bytes=max_file_bytes,
            max_total_bytes=max_total_bytes,
        )
