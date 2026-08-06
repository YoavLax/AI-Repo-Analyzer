"""AgentCompass server tests: API contract, error mapping, local-path confinement,
SPA serving. All GitHub traffic is faked via the injectable fetcher."""
import json
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from airx_server.app import create_app  # noqa: E402
from airx_server.config import Settings  # noqa: E402
from tests.test_ingest import REPO_FILES, FakeFetcher  # noqa: E402


def _settings(**overrides) -> Settings:
    base = dict(allow_local_paths=False, local_repos_root=None, static_dir=None,
                max_concurrent_analyses=2, max_fetch_files=400,
                max_file_bytes=2 * 1024 * 1024, max_total_bytes=20 * 1024 * 1024)
    base.update(overrides)
    return Settings(**base)


def _client(settings=None, fetcher=None) -> TestClient:
    return TestClient(create_app(settings or _settings(), fetcher=fetcher))


def test_health_and_version():
    client = _client()
    assert client.get("/api/health").json() == {"status": "ok"}
    version = client.get("/api/version").json()
    assert version["local_mode"] is False
    assert version["version"]


def test_analyze_remote_happy_path():
    client = _client(fetcher=FakeFetcher(REPO_FILES))
    response = client.post("/api/analyze", json={"source": "https://github.com/o/r"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["score"]["grade"]
    assert data["target"] == {"root": "github.com/o/r"}
    assert data["meta"]["mode"] == "online-scan"
    assert data["meta"]["listed_files"] == len(REPO_FILES)
    assert data["meta"]["fetched_files"] < data["meta"]["listed_files"]


def test_analyze_remote_degrades_and_discloses_when_over_budget():
    """A repository that does not fit the configured budget still returns a
    report — with the shortfall in `caveats` and counted in `meta`.

    Scoring a subset silently, as though it were the whole repository, is the
    one outcome worse than refusing outright; refusing outright was the old
    behaviour and made every large repository a limits-tuning exercise.
    """
    client = _client(_settings(max_fetch_files=1), fetcher=FakeFetcher(REPO_FILES))
    response = client.post("/api/analyze", json={"source": "o/r"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["score"]["grade"]
    assert data["meta"]["fetched_files"] == 1
    assert data["meta"]["skipped_files"] > 0
    disclosure = [c for c in data["caveats"] if "skipped" in c]
    assert disclosure, "a partial scan must say so"
    assert "MAX_FETCH_FILES" in disclosure[0], "name the limit an operator would raise"


def test_analyze_remote_reports_no_skip_caveat_when_everything_fits():
    """The disclosure must be absent on the normal path, or it becomes noise
    that gets ignored on the one scan where it matters."""
    client = _client(fetcher=FakeFetcher(REPO_FILES))
    data = client.post("/api/analyze", json={"source": "o/r"}).json()
    assert data["meta"]["skipped_files"] == 0
    assert not [c for c in data["caveats"] if "skipped" in c]


def test_analyze_report_is_deterministic_across_requests():
    client = _client(fetcher=FakeFetcher(REPO_FILES))
    payload = {"source": "o/r"}
    first = client.post("/api/analyze", json=payload).json()
    second = client.post("/api/analyze", json=payload).json()
    first.pop("meta")
    second.pop("meta")
    assert first == second


def test_analyze_rejects_bad_source():
    client = _client()
    response = client.post("/api/analyze", json={"source": "https://evil.com/o/r"})
    assert response.status_code == 400
    assert "GitHub" in response.json()["error"]["message"]


def test_analyze_requires_exactly_one_input():
    client = _client()
    assert client.post("/api/analyze", json={}).status_code == 400
    assert client.post("/api/analyze", json={"source": "o/r", "path": "x"}).status_code == 400


def test_analyze_defaults_to_platform_all():
    client = _client(fetcher=FakeFetcher(REPO_FILES))
    data = client.post("/api/analyze", json={"source": "o/r"}).json()
    assert data["platform"] == "all"


def test_analyze_honors_platform_filter():
    client = _client(fetcher=FakeFetcher(REPO_FILES))
    all_report = client.post("/api/analyze", json={"source": "o/r", "platform": "all"}).json()
    claude_report = client.post("/api/analyze", json={"source": "o/r", "platform": "claude"}).json()
    assert claude_report["platform"] == "claude"
    # A platform-scoped report evaluates a subset of rules, so it must not
    # simply equal the unfiltered ("all") pillar/finding set.
    assert claude_report["pillars"] != all_report["pillars"] or claude_report["findings"] != all_report["findings"]
    # Sub-scores are always computed unfiltered regardless of the active filter.
    assert claude_report["score"]["copilot"] == all_report["score"]["copilot"]
    assert claude_report["score"]["claude"] == all_report["score"]["claude"]


def test_analyze_rejects_invalid_platform():
    client = _client(fetcher=FakeFetcher(REPO_FILES))
    response = client.post("/api/analyze", json={"source": "o/r", "platform": "vscode"})
    assert response.status_code == 400
    assert "platform" in response.json()["error"]["message"]


def test_local_mode_disabled_by_default():
    client = _client()
    response = client.post("/api/analyze", json={"path": "some-repo"})
    assert response.status_code == 422
    assert "ALLOW_LOCAL_PATHS" in response.json()["error"]["message"]


def test_local_mode_analyzes_repo_under_root(tmp_path):
    repo = tmp_path / "team-repo"
    (repo / ".github").mkdir(parents=True)
    (repo / "CLAUDE.md").write_text("# X\n\n## Overview\nRepo.\n", encoding="utf-8")
    client = _client(_settings(allow_local_paths=True, local_repos_root=tmp_path.resolve()))
    response = client.post("/api/analyze", json={"path": "team-repo"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["meta"]["mode"] == "local-path"
    assert data["target"] == {"root": "team-repo"}


def test_local_mode_confines_to_root(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    client = _client(_settings(allow_local_paths=True, local_repos_root=root.resolve()))

    assert client.post("/api/analyze", json={"path": "../outside"}).status_code == 400
    assert client.post("/api/analyze", json={"path": "/etc"}).status_code == 400
    assert client.post("/api/analyze", json={"path": "missing"}).status_code == 404

    link = root / "sneaky"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable on this host")
    assert client.post("/api/analyze", json={"path": "sneaky"}).status_code == 400


def test_spa_fallback_serves_index(tmp_path):
    static = tmp_path / "dist"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>agentcompass</html>", encoding="utf-8")
    (static / "assets" / "main.js").write_text("console.log(1)", encoding="utf-8")
    client = _client(_settings(static_dir=static.resolve()))

    assert "agentcompass" in client.get("/").text
    assert "agentcompass" in client.get("/some/spa/route").text
    assert client.get("/assets/main.js").status_code == 200
    assert client.get("/api/nope").status_code == 404


def _ndjson(response) -> list[dict]:
    """Parse an NDJSON body into its objects, rejecting malformed lines."""
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_analyze_stream_reports_real_counts_then_the_report():
    client = _client(fetcher=FakeFetcher(REPO_FILES))
    response = client.post("/api/analyze/stream", json={"source": "o/r"})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/x-ndjson")

    events = _ndjson(response)
    assert events[-1]["type"] == "result", events[-1]
    assert all(e["type"] == "progress" for e in events[:-1])

    report = events[-1]["report"]
    progress = events[:-1]
    phases = [e["phase"] for e in progress]
    # Ordered, and every phase of the pipeline is represented.
    assert phases[0] == "resolving"
    assert "listing" in phases and "fetching" in phases and phases[-1] == "scoring"

    # The counts are the real ones, not a synthetic ramp: the listing phase
    # reports the tree size and the fetch phase ends at the file count that
    # actually landed in the snapshot.
    listing = [e for e in progress if e["phase"] == "listing"][-1]
    assert listing["total"] == report["meta"]["listed_files"] == len(REPO_FILES)
    fetching = [e for e in progress if e["phase"] == "fetching"]
    assert fetching[-1]["done"] == fetching[-1]["total"] > 0
    # Monotone within the phase — a bar driven by this can never run backwards.
    assert [e["done"] for e in fetching] == sorted(e["done"] for e in fetching)


def test_analyze_stream_returns_byte_identical_report_to_plain_analyze():
    """Determinism (D1) must not depend on whether anyone is watching."""
    plain = _client(fetcher=FakeFetcher(REPO_FILES)).post(
        "/api/analyze", json={"source": "o/r"},
    ).json()
    streamed = _ndjson(
        _client(fetcher=FakeFetcher(REPO_FILES)).post("/api/analyze/stream", json={"source": "o/r"}),
    )[-1]["report"]

    plain.pop("meta"), streamed.pop("meta")  # duration_ms is wall-clock
    assert json.dumps(streamed, sort_keys=True) == json.dumps(plain, sort_keys=True)


def test_analyze_stream_delivers_failures_as_a_terminal_error_event():
    client = _client(fetcher=FakeFetcher(REPO_FILES))
    response = client.post("/api/analyze/stream", json={"source": "not a repo url"})
    # The request itself was well-formed, so the failure arrives in the stream.
    events = _ndjson(response)
    assert events[-1]["type"] == "error"
    assert events[-1]["error"]["code"] == 400


def test_analyze_stream_rejects_a_malformed_request_before_streaming():
    client = _client(fetcher=FakeFetcher(REPO_FILES))
    response = client.post("/api/analyze/stream", json={"source": "o/r", "path": "x"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == 400
