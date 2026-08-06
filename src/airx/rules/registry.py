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

RULESET_VERSION = "0.4.0"

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
    #: Mandatory for SPEC-sourced ERROR rules — see `rule()`.
    spec_quote: str = ""


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
):
    """Decorator that registers a rule function into the global registry.

    Two gates stand between a rule and ERROR severity, because an ERROR caps
    the grade and is the strongest thing this tool says about someone's
    repository.

    *Advisory* rules must not be ERROR at all (plan-v2-fable.md §0.3): only
    objective, spec-verifiable failures may trigger the cap. The narrow
    exceptions (secret shapes, permission bypass, committed local files) are
    listed in `_ADVISORY_ERROR_ALLOWLIST`.

    *Spec* rules must quote the sentence they rest on. `source=SPEC` was the
    way around the first gate: set it, point `doc_url` at a plausible page, and
    ship. `skills.references.escape` did exactly that — ERROR, weight 6,
    `doc_url` at the spec's file-references section, asserting a
    self-containment requirement and a CWE-59 vulnerability that section does
    not mention. It produced 533 findings across 35 repositories before anyone
    read the page. `spec_quote` makes the author paste the sentence, which is
    an honest question ("which sentence?") that cannot be answered when there
    isn't one. It is checked for existence here and read by a human in review;
    the point is to force the lookup, not to verify prose automatically.
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
        if source == RuleSource.SPEC and severity == Severity.ERROR and not spec_quote.strip():
            raise ValueError(
                f"rule {id}: a spec-sourced ERROR must carry spec_quote=, the verbatim "
                f"sentence from {doc_url or 'its doc_url'} that states the requirement. "
                f"If no such sentence exists, the rule is not spec-sourced."
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
