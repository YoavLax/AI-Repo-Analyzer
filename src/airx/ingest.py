"""Clone-free GitHub snapshot ingestion (plan-v3-codecompass.md §2).

Builds a `RepoTree` for the deterministic pipeline without `git clone`: one
GitHub Trees API call yields the complete file listing, and only the files the
rules actually read — classified artifacts, the four probe files, and skill
directories — are fetched and materialized into a temp directory. Name-only
rules (globs, language histograms, CI detection) see the full listing; content
rules see real files. Everything else in the repository is never downloaded.

This module is the network quarantine: it runs strictly *before* the pipeline,
like the CLI's clone path. The analysis itself stays a pure function of the
resulting snapshot. All HTTP goes through an injectable `Fetcher`, so the test
suite never touches the network, and only two hosts are ever contacted:
`api.github.com` and `raw.githubusercontent.com` (SSRF containment).
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from airx.fs import DEFAULT_EXCLUDED_DIRS, DEFAULT_MAX_FILES, RepoTree
from airx.patterns import classify

API_HOST = "https://api.github.com"
RAW_HOST = "https://raw.githubusercontent.com"

MAX_FETCH_FILES = 400
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
#: The recursive Trees response for a ~100k-entry repository is tens of MB —
#: bounded, but far above the per-file cap.
MAX_API_RESPONSE_BYTES = 64 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30
#: Parallel raw-file fetches. Bounded to stay well inside GitHub's abuse
#: limits while turning dozens of sequential round trips into a few batches.
FETCH_CONCURRENCY = 8

#: Files probe.py reads by content; everything else it derives from names.
#: `.airx.yml` is included so a web analysis honors the same repository
#: configuration (profile, waivers, ignores) the CLI would apply.
PROBE_CONTENT_FILES = frozenset({
    "package.json", "Makefile", "pyproject.toml", ".gitignore", ".airx.yml",
})

_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_GIT_SYMLINK_MODE = "120000"

_URL_FORMS = (
    re.compile(r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?(?:/tree/(?P<ref>[^?#]+))?/?(?:[?#].*)?$"),
    re.compile(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$"),
    re.compile(r"^ssh://git@github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$"),
    re.compile(r"^(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)$"),
)


class IngestError(Exception):
    """A user-facing ingestion failure with an HTTP-ish status for the API layer."""

    def __init__(self, user_message: str, status: int = 400):
        super().__init__(user_message)
        self.user_message = user_message
        self.status = status


@dataclass(frozen=True)
class RemoteRepo:
    owner: str
    repo: str
    ref: str | None = None


@dataclass(frozen=True)
class SnapshotStats:
    listed_files: int
    fetched_files: int
    fetched_bytes: int
    resolved_sha: str


def parse_github_url(text: str) -> RemoteRepo | None:
    """Parse a GitHub URL or `owner/repo` shorthand; None when it isn't one.

    Only github.com forms are accepted — this function is the SSRF gate: no
    other host can ever reach the fetcher.
    """
    text = text.strip()
    if not text:
        return None
    for pattern in _URL_FORMS:
        match = pattern.match(text)
        if not match:
            continue
        owner = match.group("owner")
        repo = match.group("repo")
        ref = (match.groupdict().get("ref") or None)
        if ref is not None:
            ref = ref.strip("/") or None
        if not _NAME_RE.match(owner) or not _NAME_RE.match(repo):
            return None
        if owner in (".", "..") or repo in (".", ".."):
            return None
        return RemoteRepo(owner=owner, repo=repo, ref=ref)
    return None


class Fetcher(Protocol):
    def get_json(self, url: str) -> Any: ...
    def get_raw(self, url: str) -> bytes: ...


class _GitHubOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-apply the host allowlist on every redirect hop, and never carry the
    token off `api.github.com`.

    Validating only the initial URL is not SSRF containment: `urlopen` follows
    3xx to arbitrary hosts and (in CPython) forwards the `Authorization`
    header across hosts and even across an https→http downgrade. Legitimate
    same-host GitHub redirects (a renamed repo 301s within api.github.com)
    keep working.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith((API_HOST + "/", RAW_HOST + "/")):
            raise IngestError("refusing to follow a redirect off GitHub", 502)
        new_request = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_request is not None and not newurl.startswith(API_HOST + "/"):
            for name in list(new_request.headers):
                if name.lower() == "authorization":
                    del new_request.headers[name]
        return new_request


_OPENER = urllib.request.build_opener(_GitHubOnlyRedirectHandler)


class UrllibFetcher:
    """Stdlib fetcher. Sends `Authorization` only to api.github.com; honors
    GITHUB_TOKEN for the 60 → 5000 req/h rate-limit upgrade."""

    def __init__(self, token: str | None = None, max_file_bytes: int = MAX_FILE_BYTES):
        self._token = token if token is not None else os.environ.get("GITHUB_TOKEN") or None
        #: Network-level read cap for get_raw — must track the caller's
        #: max_file_bytes, or a raised fetch_snapshot() cap is silently
        #: re-clamped back down to the module default at the HTTP layer.
        self._max_file_bytes = max_file_bytes

    def _open(self, url: str, accept: str):
        if not url.startswith((API_HOST + "/", RAW_HOST + "/")):
            raise IngestError("refusing to fetch a non-GitHub URL", 400)
        headers = {"User-Agent": "agentcompass", "Accept": accept}
        if self._token and url.startswith(API_HOST + "/"):
            headers["Authorization"] = f"Bearer {self._token}"
        request = urllib.request.Request(url, headers=headers)
        return _OPENER.open(request, timeout=REQUEST_TIMEOUT_SECONDS)

    @staticmethod
    def _read_capped(response, limit: int) -> bytes:
        """Read at most `limit` bytes. A lying or absent Content-Length must
        not let a hostile response exhaust memory before the post-hoc size
        check in `fetch_snapshot`."""
        content = response.read(limit + 1)
        if len(content) > limit:
            raise IngestError(
                f"a GitHub response exceeded the {limit // (1024 * 1024)} MB read limit", 413,
            )
        return content

    def get_json(self, url: str) -> Any:
        with self._open(url, "application/vnd.github+json") as response:
            return json.loads(self._read_capped(response, MAX_API_RESPONSE_BYTES).decode("utf-8"))

    def get_raw(self, url: str) -> bytes:
        with self._open(url, "*/*") as response:
            return self._read_capped(response, self._max_file_bytes)


def _map_http_error(exc: urllib.error.HTTPError, remote: RemoteRepo) -> IngestError:
    if exc.code == 404:
        return IngestError(
            f"{remote.owner}/{remote.repo} was not found on GitHub — it may be private. "
                f"For private repositories, self-host AgentCompass and use local-path mode.",
            404,
        )
    if exc.code in (403, 429):
        remaining = exc.headers.get("x-ratelimit-remaining") if exc.headers else None
        if remaining == "0":
            return IngestError(
                "GitHub API rate limit exceeded — set GITHUB_TOKEN on the server to raise the limit.",
                429,
            )
        return IngestError("GitHub refused the request (HTTP 403).", 403)
    return IngestError(f"GitHub returned HTTP {exc.code}.", 502)


def _get_json(fetcher: Fetcher, url: str, remote: RemoteRepo) -> Any:
    try:
        return fetcher.get_json(url)
    except IngestError:
        raise
    except urllib.error.HTTPError as exc:
        raise _map_http_error(exc, remote) from exc
    except urllib.error.URLError as exc:
        raise IngestError(f"GitHub is unreachable: {exc.reason}", 502) from exc
    except (OSError, json.JSONDecodeError) as exc:
        # Read-phase failures (reset connection, timeout, truncated body) are
        # not URLError; without this they would surface as an opaque 500.
        raise IngestError(f"GitHub request failed: {exc}", 502) from exc


def _safe_rel_path(raw: str) -> PurePosixPath | None:
    """Validate a tree-listed path before it is ever joined to a local dir.

    Also drops paths inside `fs.DEFAULT_EXCLUDED_DIRS` so the listing matches
    exactly what `fs.scan` would have produced for a clone: a repository that
    commits `node_modules/` or `dist/` must score the same through the web
    scan as through the CLI.
    """
    if not raw or raw.startswith("/") or "\\" in raw or ":" in raw:
        return None
    path = PurePosixPath(raw)
    if any(part in ("..", ".", "") for part in path.parts):
        return None
    if any(part in DEFAULT_EXCLUDED_DIRS for part in path.parts[:-1]):
        return None
    return path


def select_paths(files: tuple[PurePosixPath, ...]) -> tuple[PurePosixPath, ...]:
    """The subset of the listing whose *contents* the rules read: classified
    artifacts, probe content files, and everything inside a skill directory."""
    skill_dirs = {
        rel.parent for rel in files
        if classify(rel) is not None and rel.name == "SKILL.md"
    }
    selected: set[PurePosixPath] = set()
    for rel in files:
        if classify(rel) is not None:
            selected.add(rel)
        elif len(rel.parts) == 1 and rel.name in PROBE_CONTENT_FILES:
            selected.add(rel)
        elif any(skill_dir in rel.parents for skill_dir in skill_dirs):
            selected.add(rel)
    return tuple(sorted(selected, key=lambda p: p.as_posix()))


def fetch_snapshot(
    remote: RemoteRepo,
    workdir: Path,
    fetcher: Fetcher | None = None,
    max_fetch_files: int = MAX_FETCH_FILES,
    max_file_bytes: int = MAX_FILE_BYTES,
    max_total_bytes: int = MAX_TOTAL_BYTES,
) -> tuple[RepoTree, SnapshotStats]:
    """Materialize a clone-free snapshot of `remote` into `workdir`.

    Returns the RepoTree (full listing, partial materialization) and stats.
    Raises IngestError with a user-facing message on every failure mode.

    `max_fetch_files`, `max_file_bytes`, and `max_total_bytes` cap how much
    this online scan will fetch individually over the network; self-hosted
    deployments can raise them via the `MAX_FETCH_FILES`, `MAX_FILE_BYTES`,
    and `MAX_TOTAL_BYTES` env vars (see `airx_server.config`).
    """
    fetcher = fetcher if fetcher is not None else UrllibFetcher(max_file_bytes=max_file_bytes)
    owner = urllib.parse.quote(remote.owner, safe="")
    repo = urllib.parse.quote(remote.repo, safe="")

    ref = remote.ref
    if ref is None:
        meta = _get_json(fetcher, f"{API_HOST}/repos/{owner}/{repo}", remote)
        ref = meta.get("default_branch") or "main"

    # Pin the whole snapshot to one commit sha so the tree listing and the raw
    # file fetches cannot straddle a concurrent push.
    commit = _get_json(
        fetcher, f"{API_HOST}/repos/{owner}/{repo}/commits/{urllib.parse.quote(ref, safe='')}", remote,
    )
    sha = commit.get("sha")
    if not isinstance(sha, str) or not sha:
        hint = (
            " A /tree/ URL pointing at a subdirectory includes the path in the ref; "
            "use the repository URL instead."
            if "/" in ref else ""
        )
        raise IngestError(
            f"could not resolve ref '{ref}' for {remote.owner}/{remote.repo}.{hint}", 404,
        )

    tree_data = _get_json(fetcher, f"{API_HOST}/repos/{owner}/{repo}/git/trees/{sha}?recursive=1", remote)
    if tree_data.get("truncated"):
        raise IngestError(
            "This repository's file tree is too large for the GitHub Trees API. "
            "Self-host AgentCompass and analyze it via local-path mode.",
            413,
        )

    listed: list[PurePosixPath] = []
    sizes: dict[PurePosixPath, int] = {}
    for entry in tree_data.get("tree", []):
        if entry.get("type") != "blob" or entry.get("mode") == _GIT_SYMLINK_MODE:
            continue
        rel = _safe_rel_path(str(entry.get("path", "")))
        if rel is None:
            continue
        listed.append(rel)
        size = entry.get("size")
        sizes[rel] = int(size) if isinstance(size, int) else 0
        if len(listed) >= DEFAULT_MAX_FILES:
            break
    listed.sort(key=lambda p: p.as_posix())

    selected = select_paths(tuple(listed))
    if len(selected) > max_fetch_files:
        raise IngestError(
            f"This repository has {len(selected)} AI-artifact files (limit {max_fetch_files}). "
            "Self-host AgentCompass and analyze it via local-path mode.",
            413,
        )
    oversized = [p for p in selected if sizes.get(p, 0) > max_file_bytes]
    if oversized:
        raise IngestError(
            f"Artifact file '{oversized[0]}' exceeds the {max_file_bytes // (1024 * 1024)} MB per-file limit.",
            413,
        )
    if sum(sizes.get(p, 0) for p in selected) > max_total_bytes:
        raise IngestError(
            f"The AI-artifact set exceeds the {max_total_bytes // (1024 * 1024)} MB total fetch limit.",
            413,
        )

    workdir = workdir.resolve()

    def _fetch_one(rel: PurePosixPath) -> tuple[PurePosixPath, bytes]:
        url = f"{RAW_HOST}/{owner}/{repo}/{sha}/{urllib.parse.quote(rel.as_posix())}"
        try:
            return rel, fetcher.get_raw(url)
        except IngestError:
            raise
        except urllib.error.HTTPError as exc:
            raise _map_http_error(exc, remote) from exc
        except urllib.error.URLError as exc:
            raise IngestError(f"GitHub is unreachable: {exc.reason}", 502) from exc
        except OSError as exc:
            raise IngestError(f"GitHub request failed: {exc}", 502) from exc

    # Fetches run concurrently — the files are independent and the request is
    # latency-bound (dozens of round trips to raw.githubusercontent.com).
    # Determinism is unaffected: the tree listing is sorted independently and
    # each file lands at its own path, so completion order cannot be observed.
    total = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=FETCH_CONCURRENCY) as pool:
        futures = [pool.submit(_fetch_one, rel) for rel in selected]
        try:
            for future in concurrent.futures.as_completed(futures):
                rel, content = future.result()
                total += len(content)
                if len(content) > max_file_bytes or total > max_total_bytes:
                    raise IngestError("fetch size limit exceeded mid-download", 413)
                target = workdir / str(rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        except BaseException:
            for future in futures:
                future.cancel()
            raise

    tree = RepoTree(root=workdir, files=tuple(listed))
    stats = SnapshotStats(
        listed_files=len(listed), fetched_files=len(selected),
        fetched_bytes=total, resolved_sha=sha,
    )
    return tree, stats
