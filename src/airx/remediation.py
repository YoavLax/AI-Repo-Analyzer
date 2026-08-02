"""Deterministic ranked remediation plan (plan.md §8.3, plan-v2-fable.md §3.8).

Each unsatisfied applicable rule's score gain is computed *exactly*: the
evaluation set is re-aggregated with that one rule's satisfaction forced to
1.0, and the gain is the resulting overall delta. This automatically captures
every nonlinearity of the aggregation (including the quality-ratio 0-to-1
fallback flip when the first presence rule of a pillar is satisfied). Entries
are ranked by `(-score_gain, effort_rank, rule_id)`.

Two refinements on top of that base model:

* `RuleMeta.implies` — a rule whose satisfaction *guarantees* another rule's
  satisfaction too (e.g. a platform-specific entry-point rule implies the
  cross-platform "some entry point exists" rule) is flipped together with it
  in the same simulation, and the implied rule is never listed as its own,
  separately-additive-looking entry.
* `RuleMeta.fix_by_platform` — when exactly one platform is in scope (the
  `--platform`/API filter), a cross-platform rule's suggested action is
  swapped for the platform-specific text, so a Copilot-scoped report never
  suggests a CLAUDE.md-only path and vice versa.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from airx import config
from airx.model import Platform
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

    platform_filter: Platform | None = (
        Platform(card.platform) if card.platform in ("copilot", "claude") else None
    )

    # Unsatisfied, applicable, non-waived candidates, indexed by rule id.
    idx_by_id: dict[str, int] = {
        ev.meta.id: i for i, ev in enumerate(card.evaluations)
        if ev.applicable and not ev.waived and ev.satisfaction < 1.0
    }
    # Rule ids automatically resolved as a side effect of another candidate's
    # fix (per RuleMeta.implies) must not be listed as their own, separate,
    # additive-looking entry.
    implied_ids: set[str] = {
        implied
        for i in idx_by_id.values()
        for implied in card.evaluations[i].meta.implies
        if implied in idx_by_id
    }

    candidates: list[tuple[float, int, str, tuple[int, ...]]] = []
    for rule_id, i in idx_by_id.items():
        if rule_id in implied_ids:
            continue
        ev = card.evaluations[i]
        flip_idxs = (i,) + tuple(idx_by_id[r] for r in ev.meta.implies if r in idx_by_id)
        fixed = list(card.evaluations)
        for j in flip_idxs:
            fixed[j] = replace(fixed[j], satisfaction=1.0)
        _, fixed_overall = _aggregate(tuple(fixed), weights)
        if fixed_overall is None:
            continue
        gain = round(fixed_overall - baseline, 2)
        if gain <= 0:
            continue
        effort_rank = EFFORT_RANK.get(ev.meta.effort, EFFORT_RANK["authoring"])
        candidates.append((gain, effort_rank, rule_id, flip_idxs))

    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))

    entries: list[RemediationEntry] = []
    for rank, (gain, _, rule_id, flip_idxs) in enumerate(candidates[:limit], start=1):
        ev = card.evaluations[flip_idxs[0]]
        paths = tuple(sorted({
            str(p) for j in flip_idxs for p, _ in card.evaluations[j].diagnostics if p is not None
        }))
        action = ev.meta.fix or ev.meta.summary
        if platform_filter is not None and ev.meta.fix_by_platform:
            action = dict(ev.meta.fix_by_platform).get(platform_filter, action)
        entries.append(RemediationEntry(
            rank=rank,
            rule_id=rule_id,
            score_gain=gain,
            effort=ev.meta.effort,
            action=action,
            summary=ev.meta.summary,
            paths=paths,
        ))
    return tuple(entries)
