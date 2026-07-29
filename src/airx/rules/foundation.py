"""Foundation pillar: presence and baseline quality of an always-on entry
point (`.github/copilot-instructions.md`, `AGENTS.md`, or `CLAUDE.md`).

Corresponds to plan.md pillar 1. This build covers presence, the
AGENTS.md-to-Claude bridge, a length curve, and a lightweight structure
heuristic; the remaining pillar-1 rules (section coverage, rationale
detection, import resolution, cross-file conflict detection) are the next
roadmap milestone (see plan.md section 12, Milestone 2).
"""
from __future__ import annotations

import re

from airx.discovery import ArtifactIndex
from airx.model import Applicability, Diagnostic, ParsedDocument, Pillar, RuleSource, Severity
from airx.rules.registry import RuleScope, rule
from airx import config

_HEADING_RE = re.compile(r"^#{1,3}\s", re.MULTILINE)


def _entrypoints(index: ArtifactIndex) -> list[ParsedDocument]:
    return [d for d in (index.copilot_instructions, index.claude_md) if d is not None]


@rule(
    id="foundation.entrypoint.present", pillar=Pillar.FOUNDATION, scope=RuleScope.REPO,
    applicability=Applicability.PRESENCE, weight=10, severity=Severity.ERROR,
    source=RuleSource.ADVISORY,
    doc_url="https://code.visualstudio.com/docs/copilot/customization/custom-instructions",
    summary="At least one always-on entry point exists (copilot-instructions.md, AGENTS.md, or CLAUDE.md).",
)
def check_entrypoint_present(index: ArtifactIndex):
    has_any = bool(index.copilot_instructions or index.agents_md_paths or index.claude_md)
    if has_any:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="foundation.entrypoint.present", severity=Severity.ERROR,
        message="No always-on AI entry point found (.github/copilot-instructions.md, AGENTS.md, or CLAUDE.md).",
    )]


@rule(
    id="foundation.copilot.entrypoint", pillar=Pillar.FOUNDATION, scope=RuleScope.REPO,
    applicability=Applicability.PRESENCE, weight=4, severity=Severity.WARNING,
    source=RuleSource.SPEC,
    doc_url="https://code.visualstudio.com/docs/copilot/customization/custom-instructions",
    summary="GitHub Copilot has an entry point (.github/copilot-instructions.md or AGENTS.md).",
)
def check_copilot_entrypoint(index: ArtifactIndex):
    if index.copilot_instructions or index.agents_md_paths:
        return 1.0, []
    return 0.0, [Diagnostic(rule_id="foundation.copilot.entrypoint", severity=Severity.WARNING,
                             message="No Copilot-visible entry point (.github/copilot-instructions.md or AGENTS.md).")]


@rule(
    id="foundation.claude.entrypoint", pillar=Pillar.FOUNDATION, scope=RuleScope.REPO,
    applicability=Applicability.PRESENCE, weight=4, severity=Severity.WARNING,
    source=RuleSource.SPEC, doc_url="https://code.claude.com/docs/en/memory",
    summary="Claude Code has an entry point (CLAUDE.md or .claude/CLAUDE.md).",
)
def check_claude_entrypoint(index: ArtifactIndex):
    if index.claude_md:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="foundation.claude.entrypoint", severity=Severity.WARNING,
        message="No CLAUDE.md found. Claude Code reads CLAUDE.md, not AGENTS.md directly — "
                "bridge it with a CLAUDE.md containing '@AGENTS.md'.",
    )]


@rule(
    id="foundation.agentsmd.bridged", pillar=Pillar.FOUNDATION, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=5, severity=Severity.WARNING,
    source=RuleSource.SPEC, doc_url="https://code.claude.com/docs/en/memory#agents-md",
    summary="If AGENTS.md exists without CLAUDE.md, it must be bridged for Claude Code to see it.",
)
def check_agentsmd_bridged(index: ArtifactIndex):
    if not index.agents_md_paths:
        return None  # N/A: no AGENTS.md to bridge
    if index.claude_md is not None:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="foundation.agentsmd.bridged", severity=Severity.WARNING,
        message="AGENTS.md exists but no CLAUDE.md bridges it. Claude Code reads CLAUDE.md, not AGENTS.md, "
                "so this repository's AGENTS.md content is invisible to Claude Code.",
    )]


@rule(
    id="foundation.entrypoint.length", pillar=Pillar.FOUNDATION, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=4, severity=Severity.WARNING,
    source=RuleSource.ADVISORY, doc_url="https://code.claude.com/docs/en/memory#write-effective-instructions",
    summary="Entry point length is in the effective range; long files reduce instruction adherence.",
)
def check_entrypoint_length(index: ArtifactIndex):
    docs = _entrypoints(index)
    if not docs:
        return None
    sats: list[float] = []
    diags: list[Diagnostic] = []
    lo_ideal, hi_ideal = config.ENTRYPOINT_IDEAL_LINES
    for doc in docs:
        n = doc.line_count
        if lo_ideal <= n <= hi_ideal:
            sats.append(1.0)
        elif n > config.ENTRYPOINT_MAX_LINES_HARD:
            sats.append(0.0)
            diags.append(Diagnostic(
                rule_id="foundation.entrypoint.length", severity=Severity.WARNING,
                message=f"{doc.path.name} is {n} lines, well past the recommended ~200-line ceiling; "
                        f"move content to path-scoped instructions or skills.",
            ))
        elif n < 5:
            sats.append(0.2)
        else:
            sats.append(0.6)
    return (sum(sats) / len(sats)), diags


@rule(
    id="foundation.entrypoint.structured", pillar=Pillar.FOUNDATION, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.WARNING,
    source=RuleSource.ADVISORY,
    doc_url="https://github.blog/ai-and-ml/github-copilot/5-tips-for-writing-better-custom-instructions-for-copilot/",
    summary="Entry point uses Markdown headings to organize distinct sections "
            "(overview, tech stack, guidelines, structure, resources).",
)
def check_entrypoint_structured(index: ArtifactIndex):
    docs = _entrypoints(index)
    if not docs:
        return None
    sats: list[float] = []
    diags: list[Diagnostic] = []
    for doc in docs:
        heading_count = len(_HEADING_RE.findall(doc.raw_text))
        if heading_count >= 2:
            sats.append(1.0)
        else:
            sats.append(0.0)
            diags.append(Diagnostic(
                rule_id="foundation.entrypoint.structured", severity=Severity.WARNING,
                message=f"{doc.path.name} has {heading_count} heading(s); use Markdown headings to cover "
                        f"project overview, tech stack, guidelines, structure, and resources.",
            ))
    return (sum(sats) / len(sats)), diags
