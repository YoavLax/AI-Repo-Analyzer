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


def test_analyze_remote_honors_configured_max_fetch_files():
    """MAX_FETCH_FILES is deployment-configurable (env var, wired via Settings)
    rather than a fixed 400 — a low cap must reject via the same 413 path."""
    client = _client(_settings(max_fetch_files=1), fetcher=FakeFetcher(REPO_FILES))
    response = client.post("/api/analyze", json={"source": "o/r"})
    assert response.status_code == 413
    assert "limit 1" in response.json()["error"]["message"]


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
