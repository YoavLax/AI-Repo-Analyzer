"""Tests for the ERROR-severity grade cap (plan.md open question 4, resolved:
any unwaived error-severity finding caps the overall grade at C)."""
from pathlib import Path

from airx import fs
from airx.discovery import build_index
from airx.scoring import score

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _score(fixture_name: str):
    tree = fs.scan(FIXTURES / fixture_name)
    return score(build_index(tree))


def test_clean_repo_is_not_capped():
    card = _score("repo_good_skill")
    assert card.has_error_finding is False
    assert card.grade_capped is False
    assert card.grade == card.raw_grade


def test_repo_with_error_finding_is_capped_at_c_even_if_raw_grade_is_better():
    """`repo_near_perfect_one_error` is byte-identical to the near-perfect
    `repo_good_skill` fixture except the skill's `name` field does not match
    its parent directory — a single ERROR-severity finding on an otherwise
    A-grade repository. This proves the cap actually engages, rather than
    merely being a no-op on an already-low score."""
    card = _score("repo_near_perfect_one_error")
    assert card.has_error_finding is True
    assert card.raw_grade in ("A", "B"), f"fixture must score A/B before capping, got {card.raw_grade}"
    assert card.grade == "C"
    assert card.grade_capped is True


def test_repo_without_that_error_scores_strictly_better_and_uncapped():
    """Sanity check: removing the one error (repo_good_skill) must not be
    capped and must outscore the capped grade numerically."""
    capped = _score("repo_near_perfect_one_error")
    clean = _score("repo_good_skill")
    assert clean.grade_capped is False
    assert clean.grade in ("A", "B")
    assert clean.overall >= capped.overall


def test_cap_never_upgrades_a_worse_than_c_grade():
    """A raw grade of D/E/F must stay D/E/F even with an error finding —
    the cap only prevents A/B, it never promotes a bad score."""
    card = _score("repo_malformed_yaml")
    assert card.has_error_finding is True
    if card.raw_grade in ("D", "E", "F"):
        assert card.grade == card.raw_grade
        assert card.grade_capped is False


def test_grade_rank_ordering_is_respected():
    from airx.scoring import _GRADE_RANK
    assert _GRADE_RANK["A"] < _GRADE_RANK["B"] < _GRADE_RANK["C"] < _GRADE_RANK["D"] < _GRADE_RANK["E"] < _GRADE_RANK["F"]
