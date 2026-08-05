"""Analysis service: bridges HTTP requests to the deterministic pipeline.

Framework-free on purpose — plain functions raising `ServiceError`, so the
whole service layer is testable without FastAPI and reusable elsewhere.
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

import airx.rules  # noqa: F401  (registers built-in rules on import)
from airx import airxfile, fs
from airx.discovery import build_index
from airx.ingest import (
    Fetcher,
    IngestError,
    SKIP_REASONS,
    SkippedFile,
    parse_github_url,
    fetch_snapshot,
    MAX_FETCH_FILES,
    MAX_FILE_BYTES,
    MAX_TOTAL_BYTES,
)
from airx.model import Platform
from airx.report import to_json_dict
from airx.scoring import score
from airx_server.config import Settings


class ServiceError(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.message = message
        self.status = status


#: How many skipped paths to name before summarizing the rest. Enough to act
#: on, few enough that a pathological repository cannot flood the report.
_SKIP_SAMPLE = 5


def _skip_caveats(skipped: tuple[SkippedFile, ...]) -> list[str]:
    """One caveat per budget that was hit, naming the files it cost.

    Grouped by reason rather than one line per file: an operator's next action
    is to raise a specific limit, and that decision is per budget.
    """
    if not skipped:
        return []
    caveats: list[str] = []
    for reason, explanation in SKIP_REASONS.items():
        paths = [s.path.as_posix() for s in skipped if s.reason == reason]
        if not paths:
            continue
        shown = ", ".join(paths[:_SKIP_SAMPLE])
        if len(paths) > _SKIP_SAMPLE:
            shown += f", and {len(paths) - _SKIP_SAMPLE} more"
        noun = "file" if len(paths) == 1 else "files"
        caveats.append(
            f"This online scan skipped {len(paths)} {noun} {explanation}, so the score "
            f"reflects less of the repository than a local analysis would: {shown}. "
            "Raise that limit on the deployment, or analyze a local clone via "
            "local-path mode, for a complete result."
        )
    return caveats


def _analyze_tree(tree: fs.RepoTree, platform: Platform | None = None) -> dict:
    """Run the pipeline exactly as the CLI does, including the analyzed
    repository's own `.airx.yml` (profile, ignores, waivers) — otherwise a web
    score would silently diverge from `airx analyze` on the same commit.

    A malformed `.airx.yml` is reported as a finding-free service error rather
    than being ignored, matching the CLI's exit-2 behavior.
    """
    try:
        config = airxfile.load(tree.root)
    except airxfile.AirxConfigError as exc:
        raise ServiceError(f"This repository's .airx.yml is invalid: {exc}", 422) from exc
    profile = (config.profile if config and config.profile else "standard")
    if profile not in ("minimal", "standard", "enterprise"):
        raise ServiceError(f"This repository's .airx.yml sets an unknown profile: {profile!r}", 422)
    index = build_index(tree)
    return to_json_dict(index, score(index, profile=profile, airx=config, platform=platform))


def analyze_remote(
    source: str,
    ref: str | None,
    fetcher: Fetcher | None = None,
    max_fetch_files: int = MAX_FETCH_FILES,
    max_file_bytes: int = MAX_FILE_BYTES,
    max_total_bytes: int = MAX_TOTAL_BYTES,
    platform: Platform | None = None,
) -> dict:
    remote = parse_github_url(source)
    if remote is None:
        raise ServiceError(
            "Enter a public GitHub repository URL (https://github.com/owner/repo) "
            "or an owner/repo shorthand.",
            400,
        )
    if ref is not None and remote.ref is None:
        remote = type(remote)(owner=remote.owner, repo=remote.repo, ref=ref)

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="agentcompass-") as workdir:
        try:
            tree, stats = fetch_snapshot(
                remote, Path(workdir), fetcher=fetcher, max_fetch_files=max_fetch_files,
                max_file_bytes=max_file_bytes, max_total_bytes=max_total_bytes,
            )
        except IngestError as exc:
            raise ServiceError(exc.user_message, exc.status) from exc
        report = _analyze_tree(tree, platform=platform)
    report["meta"] = {
        "source": f"{remote.owner}/{remote.repo}",
        "ref": remote.ref,
        "resolved_sha": stats.resolved_sha,
        "listed_files": stats.listed_files,
        "fetched_files": stats.fetched_files,
        "fetched_bytes": stats.fetched_bytes,
        "skipped_files": len(stats.skipped),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "mode": "online-scan",
    }
    # A partial scan still produces a useful report, but the caller has to be
    # told — silently scoring a subset as though it were the whole repository
    # is the one outcome worse than refusing outright.
    report["caveats"] = list(report["caveats"]) + _skip_caveats(stats.skipped)
    # The report's target root is an ephemeral temp dir — meaningless to the
    # caller and non-deterministic; replace it with the repo identity.
    report["target"] = {"root": f"github.com/{remote.owner}/{remote.repo}"}
    return report


def analyze_local(path_arg: str, settings: Settings, platform: Platform | None = None) -> dict:
    if not settings.allow_local_paths or settings.local_repos_root is None:
        raise ServiceError(
            "Local-path analysis is disabled on this deployment. "
            "Set ALLOW_LOCAL_PATHS=true and LOCAL_REPOS_ROOT to enable it.",
            422,
        )
    root = settings.local_repos_root
    if Path(path_arg).is_absolute() or "\\" in path_arg:
        raise ServiceError("Provide a path relative to the configured repos root.", 400)

    candidate = (root / path_arg).resolve()
    if not candidate.is_relative_to(root):
        raise ServiceError("Path escapes the configured repos root.", 400)
    if not candidate.is_dir():
        raise ServiceError(f"No repository directory at '{path_arg}' under the repos root.", 404)

    started = time.monotonic()
    tree = fs.scan(candidate)
    report = _analyze_tree(tree, platform=platform)
    report["meta"] = {
        "source": path_arg,
        "ref": None,
        "resolved_sha": None,
        "listed_files": len(tree.files),
        "fetched_files": len(tree.files),
        "fetched_bytes": 0,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "mode": "local-path",
    }
    report["target"] = {"root": path_arg}
    return report
