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
from functools import cached_property
from pathlib import Path, PurePosixPath

DEFAULT_MAX_FILES = 200_000
DEFAULT_EXCLUDED_DIRS = frozenset({
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".tox", "dist", "build", ".next", ".turbo",
})


@dataclass(frozen=True)
class RepoTree:
    """A repository listing plus the subset of it whose bytes are on disk.

    `files` is what the repository contains; `materialized` is what this
    snapshot can actually read. They differ only for a clone-free snapshot that
    hit a fetch budget (see `airx.ingest`), and keeping the difference in the
    data — rather than discovering it when a read fails — is what lets the
    analysis tell "this file is absent" apart from "this file is broken".
    Without it a `FileNotFoundError` is indistinguishable from malformed YAML,
    and an unfetched artifact is reported as a defect of the repository.
    """

    root: Path
    files: tuple[PurePosixPath, ...]  # repo-relative, POSIX-normalized, sorted
    #: Paths whose contents were materialized under `root`. None means "all of
    #: them", which is the case for any real checkout — so a local scan and a
    #: complete remote fetch are the same thing to every consumer.
    materialized: frozenset[PurePosixPath] | None = None

    def has_content(self, rel: PurePosixPath) -> bool:
        """Whether `rel`'s bytes can be read from this snapshot."""
        return self.materialized is None or rel in self.materialized

    def resolves(self, posix_path: str) -> bool:
        """Whether the listing contains this file, or a directory holding one.

        The existence question every rule should be asking. `files` already
        excludes symlinks and the excluded directories, so answering from it
        gives the scanned-tree semantics those rules want (D4/D9) — and unlike
        a `Path.is_file()` probe it stays true for a file the repository has
        but this snapshot did not fetch. A reference to a directory resolves
        when the directory holds at least one visible file, matching the
        convention of linking a folder rather than one of its files.
        """
        candidate = posix_path.strip("/")
        return candidate in self._listed_files or candidate in self._listed_dirs

    @cached_property
    def _listed_files(self) -> frozenset[str]:
        return frozenset(rel.as_posix() for rel in self.files)

    @cached_property
    def _listed_dirs(self) -> frozenset[str]:
        """Every ancestor directory of a listed file — so an empty directory,
        which a scan would never record, is correctly absent."""
        dirs: set[str] = set()
        for rel in self.files:
            parent = rel.parent
            while parent != PurePosixPath("."):
                posix = parent.as_posix()
                if posix in dirs:
                    break  # this branch was walked already
                dirs.add(posix)
                parent = parent.parent
        return frozenset(dirs)


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
