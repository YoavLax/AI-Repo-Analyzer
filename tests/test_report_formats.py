"""Report-format tests: schema compatibility, determinism, renderers."""
import json
from pathlib import Path

from airx import fs
from airx.discovery import build_index
from airx.report import to_json, to_json_dict, to_markdown, to_sarif, to_terminal
from airx.scoring import score

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _analyze(fixture_name: str):
    tree = fs.scan(FIXTURES / fixture_name)
    index = build_index(tree)
    return index, score(index)


def test_json_keeps_v01_keys_and_adds_v02_keys():
    index, card = _analyze("repo_good_skill")
    data = to_json_dict(index, card)
    # v0.1.0 keys, preserved verbatim.
    assert {"schema_version", "tool_version", "target", "score", "pillars", "inventory", "findings"} <= set(data)
    assert {"overall", "grade", "raw_grade", "grade_capped", "has_error_finding"} <= set(data["score"])
    assert {"skills_found", "skill_parse_errors", "copilot_instructions", "agents_md", "claude_md"} <= set(data["inventory"])
    # v0.2.0 additions.
    assert data["schema_version"] == "0.2.0"
    assert {"ruleset_version", "profile", "waivers", "expired_waivers", "ignored_rules",
            "remediation_plan", "caveats"} <= set(data)
    assert {"copilot", "claude", "parity_delta"} <= set(data["score"])
    assert "artifacts" in data["inventory"] and "repo_facts" in data["inventory"]
    for finding in data["findings"]:
        assert {"why", "fix", "effort"} <= set(finding)


def test_all_renderers_are_deterministic():
    for renderer in (to_json, to_markdown, to_sarif, to_terminal):
        index, card = _analyze("repo_bad_skill")
        first = renderer(index, card)
        index2, card2 = _analyze("repo_bad_skill")
        assert renderer(index2, card2) == first


def test_markdown_contains_headline_and_findings():
    index, card = _analyze("repo_bad_skill")
    md = to_markdown(index, card)
    assert md.startswith("# AI Readiness Report")
    assert "## Pillars" in md
    assert "skills.name.dirname-match" in md


def test_sarif_is_valid_and_maps_levels():
    index, card = _analyze("repo_bad_skill")
    sarif = json.loads(to_sarif(index, card))
    assert sarif["version"] == "2.1.0"
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "airx"
    assert run["tool"]["driver"]["rules"], "driver must publish the rule catalog"
    levels = {r["level"] for r in run["results"]}
    assert levels <= {"error", "warning", "note"}
    assert any(r["level"] == "error" for r in run["results"])


def test_terminal_shows_platform_scores_and_top_fixes():
    index, card = _analyze("repo_bad_skill")
    text = to_terminal(index, card)
    assert "Platforms:" in text
    assert "Top fixes" in text
