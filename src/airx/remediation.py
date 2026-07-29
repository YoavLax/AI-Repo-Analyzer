"""Deterministic ranked remediation plan (plan.md §8.3, plan-v2-fable.md §3.8).

Each unsatisfied applicable rule's score gain is computed *exactly*: the
evaluation set is re-aggregated with that one rule's satisfaction forced to
1.0, and the gain is the resulting overall delta. This automatically captures
every nonlinearity of the aggregation (including the quality-ratio 0-to-1
fallback flip when the first presence rule of a pillar is satisfied). Entries
are ranked by `(-score_gain, effort_rank, rule_id)`.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from airx import config
from airx.rules.registry import EFFORT_RANK
from airx.scoring import ScoreCard, _aggregate


@dataclass(frozen=True)
class RemediationEntry:
    rank: int
    rule_id: str
    score_gain: float
    effort: str
    action: str
    summary: str
    paths: tuple[str, ...]


def build_plan(card: ScoreCard, limit: int = 10) -> tuple[RemediationEntry, ...]:
    weights = config.PROFILES[card.profile]
    _, baseline = _aggregate(card.evaluations, weights)
    if baseline is None:
        return ()

    candidates: list[tuple[float, int, str, int]] = []
    for i, ev in enumerate(card.evaluations):
        if not ev.applicable or ev.waived or ev.satisfaction >= 1.0:
            continue
        fixed = (
            card.evaluations[:i]
            + (replace(ev, satisfaction=1.0),)
            + card.evaluations[i + 1:]
        )
        _, fixed_overall = _aggregate(fixed, weights)
        if fixed_overall is None:
            continue
        gain = round(fixed_overall - baseline, 2)
        if gain <= 0:
            continue
        effort_rank = EFFORT_RANK.get(ev.meta.effort, EFFORT_RANK["authoring"])
        candidates.append((gain, effort_rank, ev.meta.id, i))

    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))

    entries: list[RemediationEntry] = []
    for rank, (gain, _, rule_id, i) in enumerate(candidates[:limit], start=1):
        ev = card.evaluations[i]
        paths = tuple(sorted({str(p) for p, _ in ev.diagnostics if p is not None}))
        entries.append(RemediationEntry(
            rank=rank,
            rule_id=rule_id,
            score_gain=gain,
            effort=ev.meta.effort,
            action=ev.meta.fix or ev.meta.summary,
            summary=ev.meta.summary,
            paths=paths,
        ))
    return tuple(entries)
