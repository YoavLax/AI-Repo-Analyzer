"""Remediation-plan ranking tests."""
from pathlib import Path

from airx import fs
from airx.discovery import build_index
from airx.model import Platform
from airx.remediation import build_plan
from airx.scoring import score

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _plan(fixture_name: str, limit: int = 10):
    tree = fs.scan(FIXTURES / fixture_name)
    index = build_index(tree)
    return build_plan(score(index), limit=limit)


def test_plan_is_ranked_by_gain_then_effort_then_id():
    plan = _plan("repo_bad_skill")
    assert plan, "a broken repo must produce remediation entries"
    assert [e.rank for e in plan] == list(range(1, len(plan) + 1))
    keys = [(-e.score_gain,) for e in plan]
    assert keys == sorted(keys), "entries must be sorted by descending gain"
    assert all(e.score_gain > 0 for e in plan)


def test_plan_respects_limit():
    assert len(_plan("repo_empty", limit=3)) <= 3


def test_clean_repo_has_smaller_plan_than_broken_repo():
    good = _plan("repo_good_skill")
    bad = _plan("repo_bad_skill")
    assert len(good) <= len(bad)


def test_entries_carry_action_and_paths():
    plan = _plan("repo_bad_skill")
    for entry in plan:
        assert entry.action, "every entry needs an actionable string"
        assert entry.effort in ("mechanical", "additive", "authoring", "organizational")


def test_implied_entrypoint_rule_is_merged_not_listed_separately():
    # repo_empty has no entry point of any kind: foundation.entrypoint.present
    # (cross-platform) and foundation.copilot/claude.entrypoint (platform-
    # specific) are all unsatisfied together. Fixing the platform-specific one
    # also satisfies the cross-platform one, so it must not appear as its own
    # separate, additive-looking entry.
    plan = _plan("repo_empty")
    rule_ids = {e.rule_id for e in plan}
    assert "foundation.entrypoint.present" not in rule_ids
    assert "foundation.copilot.entrypoint" in rule_ids
    assert "foundation.claude.entrypoint" in rule_ids


def test_platform_scoped_fix_text_omits_other_platform_paths():
    tree = fs.scan(FIXTURES / "repo_empty")
    index = build_index(tree)

    copilot_plan = build_plan(score(index, platform=Platform.COPILOT))
    copilot_entry = next(e for e in copilot_plan if e.rule_id == "foundation.copilot.entrypoint")
    assert "CLAUDE.md" not in copilot_entry.action

    claude_plan = build_plan(score(index, platform=Platform.CLAUDE))
    claude_entry = next(e for e in claude_plan if e.rule_id == "foundation.claude.entrypoint")
    assert ".github/copilot-instructions.md" not in claude_entry.action
