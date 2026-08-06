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

import inspect
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from airx.discovery import ArtifactIndex
from airx.model import Applicability, Diagnostic, ParsedDocument, Pillar, Platform, RuleSource, Severity

RuleResult = tuple[float, list[Diagnostic]] | None

RULESET_VERSION = "0.5.0"

#: Effort classes for the remediation plan, cheapest first (plan-v2-fable.md §3.8).
EFFORT_RANK: dict[str, int] = {
    "mechanical": 0,
    "additive": 1,
    "authoring": 2,
    "organizational": 3,
}

_ALL_PLATFORMS: tuple[Platform, ...] = (Platform.COPILOT, Platform.CLAUDE)


class RuleScope(str, Enum):
    SKILL = "skill"
    REPO = "repo"


SkillRuleFn = Callable[[ParsedDocument], RuleResult]
RepoRuleFn = Callable[[ArtifactIndex], RuleResult]
#: A skill rule that also needs repository-wide context — the file listing, for
#: instance, which is the only honest way to answer "does this path exist?"
#: without probing a filesystem the snapshot may only partly hold.
SkillRuleWithIndexFn = Callable[[ParsedDocument, ArtifactIndex], RuleResult]


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
    platforms: tuple[Platform, ...] = _ALL_PLATFORMS
    why: str = ""
    fix: str = ""
    effort: str = "authoring"
    #: Per-platform override for `fix`, as (Platform, text) pairs. Used by the
    #: remediation plan when a single `--platform` filter is active, so a
    #: cross-platform rule's suggested action only names paths relevant to
    #: that platform (e.g. omit CLAUDE.md under `--platform copilot`).
    fix_by_platform: tuple[tuple[Platform, str], ...] = ()
    #: IDs of other rules that this rule's satisfaction *also* guarantees
    #: (e.g. a platform-specific entry-point rule implies the cross-platform
    #: "some entry point exists" rule). The remediation plan uses this to
    #: avoid listing both as separate, additive-looking top fixes for what is
    #: really a single action.
    implies: tuple[str, ...] = ()
    #: True for a SKILL-scope rule declared as `fn(doc, index)`. Derived from
    #: the signature at registration, so a rule opts in simply by asking for
    #: the argument rather than by setting a flag that could disagree with it.
    wants_index: bool = False
    #: The sentence at `doc_url` that establishes the requirement, verbatim.
    #: Every ERROR rule carries this or `objective_basis` — see `rule()`.
    spec_quote: str = ""
    #: For an ERROR that needs no specification to license it (unparseable
    #: JSON, a credential-shaped literal): one sentence on what makes the
    #: failure a fact rather than a preference. Mutually exclusive with
    #: `spec_quote`.
    objective_basis: str = ""


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
    platforms: tuple[Platform, ...] = _ALL_PLATFORMS,
    why: str = "",
    fix: str = "",
    effort: str = "authoring",
    fix_by_platform: tuple[tuple[Platform, str], ...] = (),
    implies: tuple[str, ...] = (),
    spec_quote: str = "",
    objective_basis: str = "",
):
    """Decorator that registers a rule function into the global registry.

    Two gates stand between a rule and ERROR severity, because an ERROR caps
    the grade and is the strongest thing this tool says about someone's
    repository.

    *Advisory* rules must not be ERROR at all (plan-v2-fable.md §0.3): only
    objective, spec-verifiable failures may trigger the cap. The narrow
    exceptions (secret shapes, permission bypass, committed local files) are
    listed in `_ADVISORY_ERROR_ALLOWLIST`.

    *Every* ERROR rule must then say what it rests on, in one of two fields.
    `spec_quote` is the verbatim sentence from `doc_url` establishing the
    requirement. `objective_basis` is for the checks no specification needs to
    license — a credential-shaped literal, JSON that does not parse, a file
    that cannot be decoded — and states in one sentence what makes the failure
    a fact rather than a preference.

    The first version of this gate covered `source=SPEC` only, which was 18 of
    the 31 ERROR rules and none of the population where the problem actually
    lived: `_ADVISORY_ERROR_ALLOWLIST` was a second door into ERROR that asked
    for nothing at all. `skills.name.reserved` came through it — advisory,
    ERROR, `doc_url` pointed at the spec's name-field section, which states
    five name constraints and no reserved-word clause, and it fired on
    Anthropic's own `claude-api` skill. `skills.description.person-voice` came
    through it telling authors to write descriptions in the third person while
    the page it cites prescribes the opposite in as many words.

    Asking "which sentence?" is a question that cannot be answered when there
    is no sentence. Both fields are checked for existence here and read by a
    human in review; the point is to force the lookup, not to verify prose.
    """

    def _decorate(fn):
        if id in _REGISTRY:
            raise ValueError(f"duplicate rule id: {id}")
        if effort not in EFFORT_RANK:
            raise ValueError(f"rule {id}: unknown effort class {effort!r}")
        if (
            source == RuleSource.ADVISORY
            and severity == Severity.ERROR
            and id not in _ADVISORY_ERROR_ALLOWLIST
        ):
            raise ValueError(
                f"rule {id}: advisory rules must not be ERROR severity "
                f"(add to _ADVISORY_ERROR_ALLOWLIST only for objective checks)"
            )
        if severity == Severity.ERROR and not (spec_quote.strip() or objective_basis.strip()):
            raise ValueError(
                f"rule {id}: an ERROR caps the grade, so it must say what it rests on. "
                f"Either spec_quote=, the verbatim sentence from "
                f"{doc_url or 'its doc_url'} that states the requirement, or "
                f"objective_basis=, one sentence on what makes the failure a fact rather "
                f"than a preference. If neither can be written, this is not an ERROR."
            )
        if spec_quote.strip() and objective_basis.strip():
            raise ValueError(
                f"rule {id}: give spec_quote= or objective_basis=, not both — "
                f"a rule rests on a cited sentence or on an observable fact, and "
                f"which one it is should be unambiguous in review."
            )
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
            platforms=tuple(platforms),
            why=why,
            fix=fix,
            effort=effort,
            fix_by_platform=tuple(fix_by_platform),
            implies=tuple(implies),
            spec_quote=spec_quote.strip(),
            objective_basis=objective_basis.strip(),
            wants_index=(
                scope == RuleScope.SKILL
                and len(inspect.signature(fn).parameters) == 2
            ),
        )
        return fn

    return _decorate


#: Advisory-source rules allowed to be ERROR because their check is objective
#: (a credential-shaped literal, a dangerous config value, a committed personal
#: file, a broken reference) rather than a stylistic heuristic.
_ADVISORY_ERROR_ALLOWLIST: frozenset[str] = frozenset({
    "foundation.entrypoint.present",
    "foundation.entrypoint.parses",
    "tooling.mcp.valid",
    "skills.name.type",
    "skills.name.reserved",
    "skills.description.type",
    "skills.description.no-xml",
    "skills.description.person-voice",
    "skills.references.resolve",
    "safety.permissions.no-bypass",
    "safety.settings.no-secrets",
    "safety.artifacts.no-secrets",
    "tooling.mcp.no-secrets",
})


def all_rules() -> tuple[RuleMeta, ...]:
    return tuple(sorted(_REGISTRY.values(), key=lambda r: r.id))


def get_rule(rule_id: str) -> RuleMeta:
    return _REGISTRY[rule_id]
