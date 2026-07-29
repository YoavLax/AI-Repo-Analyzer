"""Determinism tests (plan.md section 3): repeated runs on the same input
must produce byte-identical JSON output."""
import json
from pathlib import Path

from airx import fs
from airx.discovery import build_index
from airx.report import to_json
from airx.scoring import score

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _analyze_json(fixture_name: str) -> str:
    tree = fs.scan(FIXTURES / fixture_name)
    index = build_index(tree)
    card = score(index)
    return to_json(index, card)


def test_repeated_runs_are_byte_identical():
    fixtures = [
        "repo_empty", "repo_good_skill", "repo_bad_skill", "repo_entrypoint_only",
        "repo_malformed_yaml", "repo_agentsmd_unbridged", "repo_near_perfect_one_error",
        "repo_quality_rich", "repo_scoped_ok", "repo_scoped_missing_applyto",
        "repo_agents_ok", "repo_agents_broken", "repo_verification_rich",
        "repo_tooling_mcp", "repo_tooling_mcp_secret", "repo_safety_local_committed",
    ]
    for fixture in fixtures:
        runs = [_analyze_json(fixture) for _ in range(10)]
        assert len(set(runs)) == 1, f"non-deterministic output for {fixture}"


def test_output_is_valid_json_with_stable_finding_order():
    rendered = _analyze_json("repo_bad_skill")
    data = json.loads(rendered)
    findings = data["findings"]
    assert findings == sorted(findings, key=lambda f: (f["path"] or "", f["line"] or 0, f["rule_id"]))
