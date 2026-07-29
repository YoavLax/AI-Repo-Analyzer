"""Rule registration and execution.

A rule is a pure function over either:
  * a single parsed skill document (`SkillRuleFn`), evaluated once per
    matching SKILL.md and aggregated by mean across files, or
  * the whole `ArtifactIndex` (`RepoRuleFn`), evaluated once per repository.

Every rule returns `None` when it is not applicable to the current input
(excluded from both the presence/quality numerator and denominator — see
plan.md section 6.3), or `(satisfaction, diagnostics)` where `satisfaction`
is a value in [0.0, 1.0]. Binary rules return `(1.0, [])` on pass or
`(0.0, [Diagnostic(...)])` on fail. The one graded rule in this build
(`skills.description.quality`) computes a continuous value directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from airx.discovery import ArtifactIndex
from airx.model import Applicability, Diagnostic, ParsedDocument, Pillar, RuleSource, Severity

RuleResult = tuple[float, list[Diagnostic]] | None


class RuleScope(str, Enum):
    SKILL = "skill"
    REPO = "repo"


SkillRuleFn = Callable[[ParsedDocument], RuleResult]
RepoRuleFn = Callable[[ArtifactIndex], RuleResult]


@dataclass(frozen=True)
class RuleMeta:
    id: str
    pillar: Pillar
    scope: RuleScope
    applicability: Applicability
    weight: int
    severity: Severity
    source: RuleSource
    doc_url: str
    summary: str
    fn: Callable


_REGISTRY: dict[str, RuleMeta] = {}


def rule(
    id: str,
    *,
    pillar: Pillar,
    scope: RuleScope,
    applicability: Applicability,
    weight: int,
    severity: Severity,
    source: RuleSource,
    doc_url: str,
    summary: str,
):
    """Decorator that registers a rule function into the global registry."""

    def _decorate(fn):
        if id in _REGISTRY:
            raise ValueError(f"duplicate rule id: {id}")
        _REGISTRY[id] = RuleMeta(
            id=id,
            pillar=pillar,
            scope=scope,
            applicability=applicability,
            weight=weight,
            severity=severity,
            source=source,
            doc_url=doc_url,
            summary=summary,
            fn=fn,
        )
        return fn

    return _decorate


def all_rules() -> tuple[RuleMeta, ...]:
    return tuple(sorted(_REGISTRY.values(), key=lambda r: r.id))


def get_rule(rule_id: str) -> RuleMeta:
    return _REGISTRY[rule_id]
