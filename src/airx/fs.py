"""Deterministic, bounded filesystem traversal.

Directory contents are always sorted by name before being returned, and the
final file list is sorted again by POSIX-normalized relative path, so
discovery order — and therefore every downstream list — is stable across
operating systems and filesystems (plan.md determinism guarantee D4).
Symlinks are never followed during discovery, which also forecloses the
CWE-59 path-traversal-via-symlink class at the traversal layer (plan.md D9).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

DEFAULT_MAX_FILES = 200_000
DEFAULT_EXCLUDED_DIRS = frozenset({
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".tox", "dist", "build", ".next", ".turbo",
})


@dataclass(frozen=True)
class RepoTree:
    root: Path
    files: tuple[PurePosixPath, ...]  # repo-relative, POSIX-normalized, sorted


def scan(
    root: Path,
    max_files: int = DEFAULT_MAX_FILES,
    excluded_dirs: frozenset[str] = DEFAULT_EXCLUDED_DIRS,
) -> RepoTree:
    root = root.resolve()
    found: list[PurePosixPath] = []

    def _walk(dir_path: Path) -> None:
        if len(found) >= max_files:
            return
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: p.name)
        except (PermissionError, OSError):
            return
        for entry in entries:
            if len(found) >= max_files:
                return
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name in excluded_dirs:
                    continue
                _walk(entry)
            elif entry.is_file():
                rel = entry.relative_to(root)
                found.append(PurePosixPath(rel.as_posix()))

    _walk(root)
    found.sort(key=lambda p: p.as_posix())
    return RepoTree(root=root, files=tuple(found))
