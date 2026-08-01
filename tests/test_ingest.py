"""Clone-free GitHub ingestion tests. All network is faked — the suite never
touches the internet."""
import json
import urllib.error
from pathlib import Path, PurePosixPath

import pytest

from airx import fs
from airx.discovery import build_index
from airx.ingest import (
    API_HOST,
    RAW_HOST,
    IngestError,
    RemoteRepo,
    fetch_snapshot,
    parse_github_url,
    select_paths,
)
from airx.report import to_json_dict
from airx.scoring import score

SHA = "a" * 40


class FakeFetcher:
    """Serves a fake GitHub repo defined by {path: content} plus tree metadata."""

    def __init__(self, files: dict[str, str], *, default_branch: str = "main",
                 truncated: bool = False, modes: dict[str, str] | None = None,
                 extra_tree_entries: list[dict] | None = None):
        self.files = files
        self.default_branch = default_branch
        self.truncated = truncated
        self.modes = modes or {}
        self.extra_tree_entries = extra_tree_entries or []
        self.raw_urls: list[str] = []

    def get_json(self, url: str):
        if url == f"{API_HOST}/repos/o/r":
            return {"default_branch": self.default_branch}
        if url.startswith(f"{API_HOST}/repos/o/r/commits/"):
            return {"sha": SHA}
        if url.startswith(f"{API_HOST}/repos/o/r/git/trees/{SHA}"):
            tree = [
                {"path": path, "type": "blob", "mode": self.modes.get(path, "100644"),
                 "size": len(content.encode())}
                for path, content in sorted(self.files.items())
            ] + self.extra_tree_entries
            return {"tree": tree, "truncated": self.truncated}
        raise AssertionError(f"unexpected JSON url: {url}")

    def get_raw(self, url: str) -> bytes:
        self.raw_urls.append(url)
        prefix = f"{RAW_HOST}/o/r/{SHA}/"
        assert url.startswith(prefix), url
        from urllib.parse import unquote
        return self.files[unquote(url[len(prefix):])].encode()


REPO_FILES = {
    "CLAUDE.md": "# X\n\n## Overview\nRepo.\n\n- Run `pytest` and re-run until the tests pass.\n",
    ".github/copilot-instructions.md": "# X\n\n## Overview\nRepo.\n",
    ".github/skills/deploy/SKILL.md": (
        "---\nname: deploy\ndescription: Deploys builds when the user asks to ship.\n---\n"
        "\nSee [helper](scripts/run.sh) when deploying.\n"
    ),
    ".github/skills/deploy/scripts/run.sh": "echo deploy --help\n",
    "package.json": json.dumps({"scripts": {"test": "vitest run", "build": "vite build", "lint": "eslint ."}}),
    ".gitignore": ".env\nnode_modules/\n",
    "pyproject.toml": "[build-system]\nrequires=['setuptools']\n",
    "Makefile": "setup:\n\tpip install -e .\n",
    "src/app.py": "print('never fetched')\n",
    "src/big/module.ts": "export {}\n",
    "tests/test_x.py": "def test_x(): pass\n",
    ".github/workflows/ci.yml": "on: push\n",
}


# --- URL parsing -------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("owner/repo", RemoteRepo("owner", "repo")),
    ("https://github.com/owner/repo", RemoteRepo("owner", "repo")),
    ("https://github.com/owner/repo.git", RemoteRepo("owner", "repo")),
    ("https://github.com/owner/repo/tree/dev", RemoteRepo("owner", "repo", "dev")),
    ("git@github.com:owner/repo.git", RemoteRepo("owner", "repo")),
    ("ssh://git@github.com/owner/repo", RemoteRepo("owner", "repo")),
])
def test_parse_accepts_github_forms(text, expected):
    assert parse_github_url(text) == expected


@pytest.mark.parametrize("text", [
    "https://evil.com/owner/repo",
    "https://github.com.evil.com/owner/repo",
    "http://localhost:8080/x/y",
    "file:///etc/passwd",
    "owner/../repo",
    "../x",
    "",
    "not a url at all",
])
def test_parse_rejects_non_github_sources(text):
    assert parse_github_url(text) is None


# --- selection ---------------------------------------------------------------

def test_select_paths_takes_artifacts_probe_and_skill_dirs():
    files = tuple(sorted((PurePosixPath(p) for p in REPO_FILES), key=lambda p: p.as_posix()))
    selected = {str(p) for p in select_paths(files)}
    assert selected == {
        "CLAUDE.md",
        ".github/copilot-instructions.md",
        ".github/skills/deploy/SKILL.md",
        ".github/skills/deploy/scripts/run.sh",
        "package.json",
        ".gitignore",
        "pyproject.toml",
        "Makefile",
    }
    assert "src/app.py" not in selected


# --- snapshot ----------------------------------------------------------------

def test_snapshot_analysis_equals_on_disk_analysis(tmp_path):
    """The clone-free snapshot must produce the byte-identical report of a
    full checkout of the same tree.

    `target.root` is the one legitimately location-dependent field, so it is
    replaced structurally rather than by string substitution — a raw replace
    would silently no-op on Windows, where JSON escapes the path separators.
    """
    disk = tmp_path / "disk"
    for rel, content in REPO_FILES.items():
        p = disk / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        # write_bytes, not write_text: on Windows text mode rewrites \n as
        # \r\n, which would make the "same tree" differ from the snapshot's
        # raw bytes and change token estimates.
        p.write_bytes(content.encode("utf-8"))
    disk_index = build_index(fs.scan(disk))
    disk_report = to_json_dict(disk_index, score(disk_index))
    disk_report["target"] = {"root": "R"}

    snap_dir = tmp_path / "snap"
    snap_dir.mkdir()
    tree, stats = fetch_snapshot(RemoteRepo("o", "r"), snap_dir, fetcher=FakeFetcher(REPO_FILES))
    snap_index = build_index(tree)
    snap_report = to_json_dict(snap_index, score(snap_index))
    snap_report["target"] = {"root": "R"}

    assert json.dumps(snap_report, indent=2) == json.dumps(disk_report, indent=2)
    assert stats.listed_files == len(REPO_FILES)
    assert stats.fetched_files == 8
    assert stats.resolved_sha == SHA


def test_snapshot_does_not_fetch_unselected_files(tmp_path):
    fetcher = FakeFetcher(REPO_FILES)
    fetch_snapshot(RemoteRepo("o", "r"), tmp_path, fetcher=fetcher)
    assert not any("src/app.py" in url for url in fetcher.raw_urls)
    assert not (tmp_path / "src/app.py").exists()


def test_symlink_blobs_and_bad_paths_are_dropped(tmp_path):
    files = dict(REPO_FILES)
    fetcher = FakeFetcher(
        files,
        modes={"CLAUDE.md": "100644"},
        extra_tree_entries=[
            {"path": "evil-link", "type": "blob", "mode": "120000", "size": 10},
            {"path": "../escape.md", "type": "blob", "mode": "100644", "size": 3},
            {"path": "/abs.md", "type": "blob", "mode": "100644", "size": 3},
            {"path": "ok/../sneaky.md", "type": "blob", "mode": "100644", "size": 3},
        ],
    )
    tree, _ = fetch_snapshot(RemoteRepo("o", "r"), tmp_path, fetcher=fetcher)
    names = {str(f) for f in tree.files}
    assert "evil-link" not in names
    assert not any(".." in n or n.startswith("/") for n in names)


def test_truncated_tree_is_rejected(tmp_path):
    with pytest.raises(IngestError) as exc:
        fetch_snapshot(RemoteRepo("o", "r"), tmp_path, fetcher=FakeFetcher(REPO_FILES, truncated=True))
    assert exc.value.status == 413


def test_oversized_artifact_is_rejected(tmp_path):
    files = dict(REPO_FILES)
    fetcher = FakeFetcher(files)
    original = fetcher.get_json

    def patched(url):
        data = original(url)
        if "git/trees" in url:
            for entry in data["tree"]:
                if entry["path"] == "CLAUDE.md":
                    entry["size"] = 3 * 1024 * 1024
        return data

    fetcher.get_json = patched
    with pytest.raises(IngestError) as exc:
        fetch_snapshot(RemoteRepo("o", "r"), tmp_path, fetcher=fetcher)
    assert exc.value.status == 413


def test_http_errors_map_to_user_messages(tmp_path):
    class Raising(FakeFetcher):
        def __init__(self, code):
            super().__init__(REPO_FILES)
            self.code = code

        def get_json(self, url):
            headers = {"x-ratelimit-remaining": "0"} if self.code == 403 else {}
            import email.message
            msg = email.message.Message()
            for k, v in headers.items():
                msg[k] = v
            raise urllib.error.HTTPError(url, self.code, "err", msg, None)

    with pytest.raises(IngestError) as not_found:
        fetch_snapshot(RemoteRepo("o", "r"), tmp_path, fetcher=Raising(404))
    assert not_found.value.status == 404
    assert "private" in not_found.value.user_message

    with pytest.raises(IngestError) as limited:
        fetch_snapshot(RemoteRepo("o", "r"), tmp_path, fetcher=Raising(403))
    assert limited.value.status == 429
    assert "GITHUB_TOKEN" in limited.value.user_message


def test_ref_pinning_uses_commit_sha_for_raw(tmp_path):
    fetcher = FakeFetcher(REPO_FILES)
    fetch_snapshot(RemoteRepo("o", "r", ref="dev"), tmp_path, fetcher=fetcher)
    assert fetcher.raw_urls
    assert all(f"/{SHA}/" in url for url in fetcher.raw_urls)


def test_parallel_fetch_is_deterministic_and_complete(tmp_path):
    """Concurrent fetching must not change the materialized snapshot: same
    files, same bytes, same report as a serial fetch."""
    import airx.ingest as ingest

    serial_dir = tmp_path / "serial"
    serial_dir.mkdir()
    original = ingest.FETCH_CONCURRENCY
    ingest.FETCH_CONCURRENCY = 1
    try:
        serial_tree, serial_stats = fetch_snapshot(
            RemoteRepo("o", "r"), serial_dir, fetcher=FakeFetcher(REPO_FILES),
        )
    finally:
        ingest.FETCH_CONCURRENCY = original

    parallel_dir = tmp_path / "parallel"
    parallel_dir.mkdir()
    parallel_tree, parallel_stats = fetch_snapshot(
        RemoteRepo("o", "r"), parallel_dir, fetcher=FakeFetcher(REPO_FILES),
    )

    assert parallel_tree.files == serial_tree.files
    assert parallel_stats.fetched_files == serial_stats.fetched_files
    assert parallel_stats.fetched_bytes == serial_stats.fetched_bytes
    for rel in select_paths(serial_tree.files):
        assert (parallel_dir / str(rel)).read_bytes() == (serial_dir / str(rel)).read_bytes()

    serial_index = build_index(serial_tree)
    parallel_index = build_index(parallel_tree)
    serial_report = to_json_dict(serial_index, score(serial_index))
    parallel_report = to_json_dict(parallel_index, score(parallel_index))
    serial_report["target"] = parallel_report["target"] = {"root": "R"}
    assert parallel_report == serial_report


def test_fetch_error_propagates_from_a_worker(tmp_path):
    class Failing(FakeFetcher):
        def get_raw(self, url: str) -> bytes:
            if url.endswith("CLAUDE.md"):
                raise IngestError("boom", 502)
            return super().get_raw(url)

    with pytest.raises(IngestError):
        fetch_snapshot(RemoteRepo("o", "r"), tmp_path, fetcher=Failing(REPO_FILES))
