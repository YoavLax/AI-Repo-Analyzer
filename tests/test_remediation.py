"""Remediation-plan ranking tests."""
from pathlib import Path

from airx import fs
from airx.discovery import build_index
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
