"""Pillar and overall score aggregation.

Implements plan.md section 6:
  * presence/quality split per pillar (6.2)
  * rule applicability / N/A handling (6.3)
  * grade bands (6.6)
  * the ERROR-severity grade cap (section 14, open question 4 — resolved:
    ANY unwaived error-severity finding caps the overall grade at C)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from airx import config
from airx.discovery import ArtifactIndex
from airx.model import Applicability, Diagnostic, Pillar, Severity
from airx.rules.registry import RuleMeta, RuleScope, all_rules


@dataclass(frozen=True)
class RuleEvaluation:
    meta: RuleMeta
    applicable: bool
    satisfaction: float  # meaningless if not applicable
    diagnostics: tuple[tuple[PurePosixPath | None, Diagnostic], ...]


@dataclass(frozen=True)
class PillarScore:
    pillar: Pillar
    weight: int
    presence_ratio: float | None
    quality_ratio: float | None
    score: float | None  # 0..1, None if the pillar has zero registered rules
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


def _relpath(index: ArtifactIndex, abs_path) -> PurePosixPath:
    try:
        return PurePosixPath(abs_path.resolve().relative_to(index.root).as_posix())
    except ValueError:
        return PurePosixPath(str(abs_path))


def evaluate(index: ArtifactIndex) -> tuple[RuleEvaluation, ...]:
    evaluations: list[RuleEvaluation] = []
    for meta in all_rules():
        if meta.scope == RuleScope.SKILL:
            docs = index.skills
            if not docs:
                evaluations.append(RuleEvaluation(meta=meta, applicable=False, satisfaction=0.0, diagnostics=()))
                continue
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
            evaluations.append(RuleEvaluation(
                meta=meta, applicable=True, satisfaction=sum(sats) / len(sats), diagnostics=tuple(diags),
            ))
        elif meta.scope == RuleScope.REPO:
            result = meta.fn(index)
            if result is None:
                evaluations.append(RuleEvaluation(meta=meta, applicable=False, satisfaction=0.0, diagnostics=()))
                continue
            sat, file_diags = result
            evaluations.append(RuleEvaluation(
                meta=meta, applicable=True, satisfaction=sat, diagnostics=tuple((None, d) for d in file_diags),
            ))
    return tuple(evaluations)


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


def score(index: ArtifactIndex) -> ScoreCard:
    evaluations = evaluate(index)

    pillar_scores: list[PillarScore] = []
    for pillar in Pillar:
        pillar_evals = [e for e in evaluations if e.meta.pillar == pillar]
        if not pillar_evals:
            pillar_scores.append(PillarScore(
                pillar=pillar, weight=config.PILLAR_WEIGHTS.get(pillar.value, 0),
                presence_ratio=None, quality_ratio=None, score=None, rule_count=0,
            ))
            continue

        presence = [e for e in pillar_evals if e.meta.applicability == Applicability.PRESENCE]
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
            pillar=pillar, weight=config.PILLAR_WEIGHTS.get(pillar.value, 0),
            presence_ratio=presence_ratio, quality_ratio=quality_ratio,
            score=pillar_score_value, rule_count=len(pillar_evals),
        ))

    scored = [p for p in pillar_scores if p.score is not None]
    total_weight = sum(p.weight for p in scored) or 1
    overall = 100.0 * sum(p.weight * p.score for p in scored) / total_weight

    has_error = any(
        e.applicable and e.satisfaction < 1.0 and e.meta.severity == Severity.ERROR
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
    )
