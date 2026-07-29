"""End-to-end tests over the fixture repos in tests/fixtures/, exercising the
full pipeline: fs.scan -> discovery.build_index -> scoring.score.
"""
from pathlib import Path

from airx import fs
from airx.discovery import build_index
from airx.scoring import score

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _score(fixture_name: str):
    tree = fs.scan(FIXTURES / fixture_name)
    index = build_index(tree)
    return index, score(index)


def _pillar(card, pillar_id: str):
    return next(p for p in card.pillars if p.pillar.value == pillar_id)


def test_empty_repo_scores_very_low():
    _, card = _score("repo_empty")
    assert card.overall < 20
    assert card.grade in ("E", "F")
    assert _pillar(card, "foundation").score == 0.0
    assert _pillar(card, "skills").score == 0.0


def test_entrypoint_only_repo_scores_higher_than_empty():
    _, card_empty = _score("repo_empty")
    _, card_entry = _score("repo_entrypoint_only")
    assert card_entry.overall > card_empty.overall
    assert _pillar(card_entry, "foundation").score > 0.5


def test_good_skill_repo_scores_higher_than_bad_skill_repo():
    _, card_good = _score("repo_good_skill")
    _, card_bad = _score("repo_bad_skill")
    good_skills = _pillar(card_good, "skills").score
    bad_skills = _pillar(card_bad, "skills").score
    assert good_skills > bad_skills
    assert card_good.overall > card_bad.overall


def test_zero_skills_scores_lower_than_one_flawed_skill():
    """Anti-gaming: having zero skills must not out-score having a flawed one."""
    _, card_empty = _score("repo_empty")
    _, card_bad = _score("repo_bad_skill")
    assert _pillar(card_empty, "skills").score <= _pillar(card_bad, "skills").score


def test_good_skill_repo_has_no_error_findings_and_is_not_capped():
    _, card = _score("repo_good_skill")
    assert card.has_error_finding is False
    assert card.grade_capped is False
    assert card.grade == card.raw_grade


def test_bad_skill_repo_has_error_findings():
    _, card = _score("repo_bad_skill")
    assert card.has_error_finding is True
    error_rules = {
        d.rule_id for ev in card.evaluations if ev.applicable
        for _, d in ev.diagnostics if d.severity.value == "error"
    }
    assert "skills.name.dirname-match" in error_rules
    assert "skills.references.resolve" in error_rules


def test_malformed_yaml_produces_parse_error_finding():
    index, card = _score("repo_malformed_yaml")
    assert len(index.skill_parse_errors) == 1
    assert card.has_error_finding is True
    parse_findings = [
        d for ev in card.evaluations if ev.meta.id == "skills.parses"
        for _, d in ev.diagnostics
    ]
    assert len(parse_findings) == 1


def test_agentsmd_without_claude_bridge_is_flagged():
    _, card = _score("repo_agentsmd_unbridged")
    bridge_findings = [
        d for ev in card.evaluations if ev.meta.id == "foundation.agentsmd.bridged"
        for _, d in ev.diagnostics
    ]
    assert len(bridge_findings) == 1
    assert "Claude Code" in bridge_findings[0].message
