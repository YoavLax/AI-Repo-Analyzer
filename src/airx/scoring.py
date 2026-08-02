"""Pillar and overall score aggregation.

Implements plan.md §6 and the v0.2.0 extensions (plan-v2-fable.md §3.6):
  * presence/quality split per pillar (§6.2) and N/A handling (§6.3)
  * weight profiles as data (§6.1)
  * `.airx.yml` waivers and ignores (§6.7) — waived rules score 1.0 and are
    excluded from the error cap; ignored rules leave the denominator entirely
  * platform sub-scores and the parity delta (§6.5)
  * grade bands (§6.6) and the ERROR-severity grade cap
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from airx import config
from airx.airxfile import AirxConfig, Waiver
from airx.discovery import ArtifactIndex
from airx.model import Applicability, Diagnostic, Pillar, Platform, Severity
from airx.rules.registry import RuleMeta, RuleScope, all_rules


@dataclass(frozen=True)
class RuleEvaluation:
    meta: RuleMeta
    applicable: bool
    satisfaction: float  # meaningless if not applicable
    diagnostics: tuple[tuple[PurePosixPath | None, Diagnostic], ...]
    waived: bool = False


@dataclass(frozen=True)
class PillarScore:
    pillar: Pillar
    weight: int
    presence_ratio: float | None
    quality_ratio: float | None
    score: float | None  # 0..1, None if the pillar has zero registered rules or zero weight
    rule_count: int


@dataclass(frozen=True)
class ScoreCard:
    pillars: tuple[PillarScore, ...]
    overall: float  # 0..100, scaled over the weight of *scored* pillars only
    grade: str
    raw_grade: str  # grade before the error cap was applied
    grade_capped: bool
    evaluations: tuple[RuleEvaluation, ...]
    has_error_finding: bool
    profile: str = "standard"
    #: "all", "copilot", or "claude" — the `--platform`/API filter applied
    #: when this card was scored. "all" means no filter (both platforms'
    #: rules count toward `overall`/`pillars`/`evaluations`).
    platform: str = "all"
    copilot: float | None = None
    claude: float | None = None
    parity_delta: float | None = None
    waived_rules: tuple[Waiver, ...] = ()
    expired_waivers: tuple[Waiver, ...] = ()
    ignored_rules: tuple[str, ...] = ()
    today: str | None = None  # the waiver-expiry evaluation date, when one was supplied


def _relpath(index: ArtifactIndex, abs_path) -> PurePosixPath:
    try:
        return PurePosixPath(abs_path.resolve().relative_to(index.root).as_posix())
    except ValueError:
        return PurePosixPath(str(abs_path))


def evaluate(
    index: ArtifactIndex,
    *,
    ignored_prefixes: tuple[str, ...] = (),
    waived_rule_ids: frozenset[str] = frozenset(),
) -> tuple[RuleEvaluation, ...]:
    evaluations: list[RuleEvaluation] = []
    for meta in all_rules():
        if any(meta.id.startswith(p) for p in ignored_prefixes if p):
            continue

        if meta.scope == RuleScope.SKILL:
            docs = index.skills
            sats: list[float] = []
            diags: list[tuple[PurePosixPath | None, Diagnostic]] = []
            for doc in docs:
                result = meta.fn(doc)
                if result is None:
                    continue
                sat, file_diags = result
                sats.append(sat)
                rel = _relpath(index, doc.path)
                diags.extend((rel, d) for d in file_diags)
            if not sats:
                evaluations.append(RuleEvaluation(meta=meta, applicable=False, satisfaction=0.0, diagnostics=()))
                continue
            satisfaction = sum(sats) / len(sats)
            diagnostics = tuple(diags)
        elif meta.scope == RuleScope.REPO:
            result = meta.fn(index)
            if result is None:
                evaluations.append(RuleEvaluation(meta=meta, applicable=False, satisfaction=0.0, diagnostics=()))
                continue
            satisfaction, file_diags = result
            diagnostics = tuple((d_path, d) for d_path, d in _normalize_repo_diags(file_diags))
        else:  # pragma: no cover - future scopes
            continue

        if meta.id in waived_rule_ids:
            evaluations.append(RuleEvaluation(
                meta=meta, applicable=True, satisfaction=1.0, diagnostics=diagnostics, waived=True,
            ))
        else:
            evaluations.append(RuleEvaluation(
                meta=meta, applicable=True, satisfaction=satisfaction, diagnostics=diagnostics,
            ))
    return tuple(evaluations)


def _normalize_repo_diags(diags) -> list[tuple[PurePosixPath | None, Diagnostic]]:
    """Repo rules may return bare Diagnostics or (path, Diagnostic) pairs."""
    out: list[tuple[PurePosixPath | None, Diagnostic]] = []
    for item in diags:
        if isinstance(item, Diagnostic):
            out.append((None, item))
        else:
            path, diag = item
            out.append((PurePosixPath(path) if path is not None else None, diag))
    return out


def _weighted_ratio(evals: list[RuleEvaluation]) -> float:
    total_weight = sum(e.meta.weight for e in evals)
    if total_weight == 0:
        return 1.0
    return sum(e.meta.weight * e.satisfaction for e in evals) / total_weight


_GRADE_RANK = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4, "F": 5}


def _grade_for(overall: float) -> str:
    for threshold, label in config.GRADE_BANDS:
        if overall >= threshold:
            return label
    return "F"


def _aggregate(
    evaluations: tuple[RuleEvaluation, ...],
    weights: dict[str, int],
    platform: Platform | None = None,
) -> tuple[list[PillarScore], float | None]:
    """Compute pillar scores and the weighted overall for one rule subset.

    Returns (pillars, overall) where overall is None when no pillar is scored
    (e.g. a platform filter that matches no rules).
    """
    if platform is not None:
        evaluations = tuple(e for e in evaluations if platform in e.meta.platforms)

    pillar_scores: list[PillarScore] = []
    for pillar in Pillar:
        weight = weights.get(pillar.value, 0)
        pillar_evals = [e for e in evaluations if e.meta.pillar == pillar]
        # A pillar is scored only when it has weight and at least one applicable
        # rule. A pillar whose every rule is N/A (e.g. the quality pillar in a
        # repo with no entry point at all) has nothing to grade — excluding it
        # beats awarding a vacuous 100% (the absence itself is already penalized
        # by the foundation pillar's presence rules).
        if not pillar_evals or weight == 0 or not any(e.applicable for e in pillar_evals):
            pillar_scores.append(PillarScore(
                pillar=pillar, weight=weight,
                presence_ratio=None, quality_ratio=None, score=None,
                rule_count=len(pillar_evals),
            ))
            continue

        presence = [
            e for e in pillar_evals
            if e.meta.applicability == Applicability.PRESENCE and e.applicable
        ]
        quality = [e for e in pillar_evals if e.meta.applicability == Applicability.QUALITY and e.applicable]

        presence_ratio = _weighted_ratio(presence) if presence else 1.0
        if quality:
            quality_ratio = _weighted_ratio(quality)
        else:
            # No applicable quality rules. If nothing is present at all,
            # there is no quality to speak of (0), not a free pass (1) —
            # otherwise deleting every artifact would still score ~60% of
            # the pillar. If something is present but simply has nothing
            # gradable (e.g. a single, simple, valid file), default to 1.
            quality_ratio = 1.0 if presence_ratio > 0 else 0.0

        pillar_score_value = (config.PRESENCE_WEIGHT * presence_ratio) + (config.QUALITY_WEIGHT * quality_ratio)
        pillar_scores.append(PillarScore(
            pillar=pillar, weight=weight,
            presence_ratio=presence_ratio, quality_ratio=quality_ratio,
            score=pillar_score_value, rule_count=len(pillar_evals),
        ))

    scored = [p for p in pillar_scores if p.score is not None]
    if not scored:
        return pillar_scores, None
    total_weight = sum(p.weight for p in scored) or 1
    overall = 100.0 * sum(p.weight * p.score for p in scored) / total_weight
    return pillar_scores, overall


def score(
    index: ArtifactIndex,
    *,
    profile: str = "standard",
    airx: AirxConfig | None = None,
    today: str | None = None,
    extra_ignore: tuple[str, ...] = (),
    no_waivers: bool = False,
    platform: Platform | None = None,
) -> ScoreCard:
    if profile not in config.PROFILES:
        raise ValueError(f"unknown profile: {profile!r} (expected one of {sorted(config.PROFILES)})")
    weights = config.PROFILES[profile]

    ignored_prefixes = tuple(extra_ignore)
    active_waivers: tuple[Waiver, ...] = ()
    expired: tuple[Waiver, ...] = ()
    if airx is not None:
        ignored_prefixes = ignored_prefixes + airx.ignore
        if not no_waivers:
            expired = airx.expired_waivers(today)
            active_waivers = tuple(w for w in airx.waivers if not w.is_expired(today))

    waived_ids = frozenset(w.rule for w in active_waivers)
    evaluations = evaluate(index, ignored_prefixes=ignored_prefixes, waived_rule_ids=waived_ids)

    # Platform sub-scores are always computed from the UNFILTERED evaluation
    # set: `--platform copilot` scopes the headline score, but must not make
    # the report claim the other platform matches it (parity delta of 0).
    _, copilot = _aggregate(evaluations, weights, platform=Platform.COPILOT)
    _, claude = _aggregate(evaluations, weights, platform=Platform.CLAUDE)
    parity_delta = (
        round(abs(copilot - claude), 2) if copilot is not None and claude is not None else None
    )

    if platform is not None:
        evaluations = tuple(e for e in evaluations if platform in e.meta.platforms)

    pillar_scores, overall_opt = _aggregate(evaluations, weights)
    overall = overall_opt if overall_opt is not None else 0.0

    has_error = any(
        e.applicable and not e.waived and e.satisfaction < 1.0 and e.meta.severity == Severity.ERROR
        for e in evaluations
    )

    raw_grade = _grade_for(overall)
    grade = raw_grade
    grade_capped = False
    if has_error and _GRADE_RANK[raw_grade] < _GRADE_RANK[config.ERROR_CAPS_GRADE_AT]:
        grade = config.ERROR_CAPS_GRADE_AT
        grade_capped = True

    return ScoreCard(
        pillars=tuple(pillar_scores), overall=round(overall, 2),
        grade=grade, raw_grade=raw_grade, grade_capped=grade_capped,
        evaluations=evaluations, has_error_finding=has_error,
        profile=profile,
        platform=platform.value if platform is not None else "all",
        copilot=round(copilot, 2) if copilot is not None else None,
        claude=round(claude, 2) if claude is not None else None,
        parity_delta=parity_delta,
        waived_rules=active_waivers,
        expired_waivers=expired,
        ignored_rules=tuple(sorted(set(ignored_prefixes))),
        today=today,
    )
