"""Foundation pillar: presence and baseline quality of an always-on entry
point (`.github/copilot-instructions.md`, `AGENTS.md`, or `CLAUDE.md`).

Corresponds to plan.md pillar 1. This build covers presence, the
AGENTS.md-to-Claude bridge, a length curve, a lightweight structure
heuristic, section-signal coverage, CLAUDE.md `@path` import resolution,
and entry-point parseability (plan-v2-fable.md §4.1).
"""
from __future__ import annotations

import itertools
import posixpath
import re
from pathlib import PurePosixPath

from airx.discovery import ArtifactIndex
from airx.model import (
    Applicability,
    ArtifactKind,
    Diagnostic,
    ParsedDocument,
    Pillar,
    Platform,
    RuleSource,
    Severity,
)
from airx.rules.registry import RuleScope, rule
from airx import markdown as md
from airx import config

_HEADING_RE = re.compile(r"^#{1,3}\s", re.MULTILINE)

# --- foundation.sections.coverage (plan-v2-fable.md §4.1) --------------------

_SECTION_HEADING_RE = re.compile(r"^#{1,6}\s.*", re.MULTILINE)
_SECTION_INTRO_CHARS = 200
#: (signal name, keyword set) in report order. A signal counts when any
#: heading line or the first `_SECTION_INTRO_CHARS` chars of the body
#: contain any keyword (case-insensitive).
_SECTION_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("overview", ("overview", "about", "purpose", "what is")),
    ("techstack", ("tech stack", "stack", "technologies", "built with", "framework", "language")),
    ("guidelines", ("guideline", "convention", "style", "standard", "rule")),
    ("structure", ("structure", "layout", "organization", "director", "folder")),
    ("resources", ("script", "command", "tooling", "resource", "mcp")),
)


def _covered_signals(doc: ParsedDocument) -> frozenset[str]:
    """The subset of `_SECTION_SIGNALS` names this document satisfies, per the
    same heading+intro-text keyword match used by `check_sections_coverage`
    (shared so `foundation.entrypoints.consistent` scores topic coverage
    identically instead of re-deriving it)."""
    headings = "\n".join(_SECTION_HEADING_RE.findall(doc.body))
    haystack = (headings + "\n" + doc.body[:_SECTION_INTRO_CHARS]).lower()
    return frozenset(
        name for name, keywords in _SECTION_SIGNALS
        if any(kw in haystack for kw in keywords)
    )

# --- foundation.imports.resolve ----------------------------------------------

#: `@path` import tokens in CLAUDE.md: an `@` at line start or after whitespace,
#: followed by a path whose first character is alphanumeric/underscore. Tokens
#: like `@AGENTS.md` count; `user@example.com` does not (no preceding space).
_IMPORT_RE = re.compile(r"(?m)(?:^|\s)@([A-Za-z0-9_][A-Za-z0-9_./-]*)")

_ENTRYPOINT_KINDS = frozenset({
    ArtifactKind.ENTRYPOINT_COPILOT,
    ArtifactKind.ENTRYPOINT_CLAUDE,
    ArtifactKind.ENTRYPOINT_GEMINI,
})


def _entrypoints(index: ArtifactIndex) -> list[ParsedDocument]:
    return list(index.entrypoint_docs())


@rule(
    id="foundation.entrypoint.present", pillar=Pillar.FOUNDATION, scope=RuleScope.REPO,
    applicability=Applicability.PRESENCE, weight=10, severity=Severity.ERROR,
    source=RuleSource.ADVISORY,
    doc_url="https://code.visualstudio.com/docs/copilot/customization/custom-instructions",
    summary="At least one always-on entry point exists (copilot-instructions.md, AGENTS.md, CLAUDE.md, or GEMINI.md).",
    why="Without an always-on entry point, AI assistants start every task with zero repository context.",
    fix="Create a .github/copilot-instructions.md, AGENTS.md, or CLAUDE.md describing the project.",
    fix_by_platform=(
        (Platform.COPILOT, "Create a .github/copilot-instructions.md or AGENTS.md describing the project."),
        (Platform.CLAUDE, "Create a CLAUDE.md (or an AGENTS.md bridged via a CLAUDE.md containing "
                          "'@AGENTS.md') describing the project."),
    ),
    effort="additive",
)
def check_entrypoint_present(index: ArtifactIndex):
    has_any = bool(
        index.copilot_instructions or index.agents_md_paths or index.claude_md or index.gemini_md
    )
    if has_any:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="foundation.entrypoint.present", severity=Severity.ERROR,
        message="No always-on AI entry point found (.github/copilot-instructions.md, AGENTS.md, "
                "CLAUDE.md, or GEMINI.md).",
    )]


@rule(
    id="foundation.copilot.entrypoint", pillar=Pillar.FOUNDATION, scope=RuleScope.REPO,
    applicability=Applicability.PRESENCE, weight=4, severity=Severity.WARNING,
    source=RuleSource.SPEC,
    doc_url="https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/add-custom-instructions/add-repository-instructions",
    summary="GitHub Copilot has an entry point (.github/copilot-instructions.md, AGENTS.md, or GEMINI.md).",
    platforms=(Platform.COPILOT,),
    why="GitHub Copilot cloud agent auto-loads .github/copilot-instructions.md, AGENTS.md, CLAUDE.md, or GEMINI.md.",
    fix="Add a .github/copilot-instructions.md (or a root AGENTS.md) with project instructions.",
    effort="additive",
    implies=("foundation.entrypoint.present",),
)
def check_copilot_entrypoint(index: ArtifactIndex):
    if index.copilot_instructions or index.agents_md_paths or index.gemini_md:
        return 1.0, []
    return 0.0, [Diagnostic(rule_id="foundation.copilot.entrypoint", severity=Severity.WARNING,
                             message="No Copilot-visible entry point (.github/copilot-instructions.md, "
                                     "AGENTS.md, or GEMINI.md).")]


@rule(
    id="foundation.claude.entrypoint", pillar=Pillar.FOUNDATION, scope=RuleScope.REPO,
    applicability=Applicability.PRESENCE, weight=4, severity=Severity.WARNING,
    source=RuleSource.SPEC, doc_url="https://code.claude.com/docs/en/memory",
    summary="Claude Code has an entry point (CLAUDE.md or .claude/CLAUDE.md).",
    platforms=(Platform.CLAUDE,),
    why="Claude Code auto-loads only CLAUDE.md; without it Claude starts with no project memory.",
    fix="Add a CLAUDE.md (or bridge an existing AGENTS.md with a CLAUDE.md containing '@AGENTS.md').",
    effort="additive",
    implies=("foundation.entrypoint.present",),
)
def check_claude_entrypoint(index: ArtifactIndex):
    if index.claude_md:
        return 1.0, []
    # The suggested fix must match what actually exists in the repo: bridging
    # to '@AGENTS.md' is only actionable when a root AGENTS.md is present.
    # Otherwise the more common case (a .github/copilot-instructions.md entry
    # point with no AGENTS.md at all, per plan-v2-fable.md's Copilot/Claude
    # parity model) needs its own bridge target instead of a nonexistent one.
    if PurePosixPath("AGENTS.md") in index.agents_md_paths:
        message = (
            "No CLAUDE.md found. Claude Code reads CLAUDE.md, not AGENTS.md directly — "
            "bridge it with a CLAUDE.md containing '@AGENTS.md'."
        )
    elif index.copilot_instructions is not None:
        message = (
            "No CLAUDE.md found. Claude Code does not read .github/copilot-instructions.md — "
            "bridge it with a CLAUDE.md containing '@.github/copilot-instructions.md'."
        )
    else:
        message = "No CLAUDE.md found; Claude Code starts every session with no project memory."
    return 0.0, [Diagnostic(
        rule_id="foundation.claude.entrypoint", severity=Severity.WARNING,
        message=message,
    )]


@rule(
    id="foundation.agentsmd.bridged", pillar=Pillar.FOUNDATION, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=5, severity=Severity.WARNING,
    source=RuleSource.SPEC, doc_url="https://code.claude.com/docs/en/memory#agents-md",
    summary="If AGENTS.md exists without CLAUDE.md, it must be bridged for Claude Code to see it.",
    platforms=(Platform.CLAUDE,),
    why="Claude Code reads CLAUDE.md, not AGENTS.md, so unbridged AGENTS.md content is invisible to it.",
    fix="Create a CLAUDE.md containing '@AGENTS.md' to bridge the existing AGENTS.md.",
    effort="mechanical",
)
def check_agentsmd_bridged(index: ArtifactIndex):
    if not index.agents_md_paths:
        return None  # N/A: no AGENTS.md to bridge
    if index.claude_md is not None:
        return 1.0, []
    path = sorted(index.agents_md_paths)[0]
    return 0.0, [(path, Diagnostic(
        rule_id="foundation.agentsmd.bridged", severity=Severity.WARNING,
        message="AGENTS.md exists but no CLAUDE.md bridges it. Claude Code reads CLAUDE.md, not AGENTS.md, "
                "so this repository's AGENTS.md content is invisible to Claude Code.",
    ))]


@rule(
    id="foundation.entrypoint.length", pillar=Pillar.FOUNDATION, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=4, severity=Severity.WARNING,
    source=RuleSource.ADVISORY, doc_url="https://code.claude.com/docs/en/memory#write-effective-instructions",
    summary="Entry point length is in the effective range; long files reduce instruction adherence.",
    why="Very long entry points dilute instruction adherence, and near-empty ones carry no signal.",
    fix="Keep the entry point near 30-150 lines and move detail into path-scoped instructions or skills.",
    effort="authoring",
)
def check_entrypoint_length(index: ArtifactIndex):
    docs = _entrypoints(index)
    if not docs:
        return None
    paths = index.entrypoint_paths()
    sats: list[float] = []
    diags: list[tuple] = []
    lo_ideal, hi_ideal = config.ENTRYPOINT_IDEAL_LINES
    for doc, path in zip(docs, paths):
        n = doc.line_count
        if lo_ideal <= n <= hi_ideal:
            sats.append(1.0)
        elif n > config.ENTRYPOINT_MAX_LINES_HARD:
            sats.append(0.0)
            diags.append((path, Diagnostic(
                rule_id="foundation.entrypoint.length", severity=Severity.WARNING,
                message=f"{doc.path.name} is {n} lines, well past the recommended ~200-line ceiling; "
                        f"move content to path-scoped instructions or skills.",
            )))
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
    why="Headings let both humans and models locate the relevant instructions quickly.",
    fix="Organize the entry point under Markdown headings such as overview, tech stack, guidelines, "
        "structure, and resources.",
    effort="authoring",
)
def check_entrypoint_structured(index: ArtifactIndex):
    docs = _entrypoints(index)
    if not docs:
        return None
    paths = index.entrypoint_paths()
    sats: list[float] = []
    diags: list[tuple] = []
    for doc, path in zip(docs, paths):
        heading_count = len(_HEADING_RE.findall(doc.raw_text))
        if heading_count >= 2:
            sats.append(1.0)
        else:
            sats.append(0.0)
            diags.append((path, Diagnostic(
                rule_id="foundation.entrypoint.structured", severity=Severity.WARNING,
                message=f"{doc.path.name} has {heading_count} heading(s); use Markdown headings to cover "
                        f"project overview, tech stack, guidelines, structure, and resources.",
            )))
    return (sum(sats) / len(sats)), diags


@rule(
    id="foundation.sections.coverage", pillar=Pillar.FOUNDATION, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=6, severity=Severity.INFO,
    source=RuleSource.ADVISORY,
    doc_url="https://github.blog/ai-and-ml/github-copilot/5-tips-for-writing-better-custom-instructions-for-copilot/",
    summary="Entry point covers the five core section signals: overview, tech stack, "
            "guidelines, structure, resources.",
    why="Entry points that cover the five core topics give assistants a complete mental model "
        "of the project up front.",
    fix="Add the missing sections (overview, tech stack, guidelines, structure, resources) "
        "to the entry point.",
    effort="authoring",
)
def check_sections_coverage(index: ArtifactIndex):
    docs = _entrypoints(index)
    if not docs:
        return None
    paths = index.entrypoint_paths()
    total = len(_SECTION_SIGNALS)
    sats: list[float] = []
    diags: list[tuple] = []
    for doc, path in zip(docs, paths):
        covered = _covered_signals(doc)
        missing = [name for name, _ in _SECTION_SIGNALS if name not in covered]
        k = len(covered)
        sats.append(k / total)
        if missing:
            diags.append((path, Diagnostic(
                rule_id="foundation.sections.coverage", severity=Severity.INFO,
                message=f"{doc.path.name} covers {k}/{total} core sections; "
                        f"missing: {', '.join(missing)}.",
            )))
    return (sum(sats) / len(sats)), diags


@rule(
    id="foundation.imports.resolve", pillar=Pillar.FOUNDATION, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.ERROR,
    source=RuleSource.SPEC, platforms=(Platform.CLAUDE,),
    doc_url="https://code.claude.com/docs/en/memory#claude-md-imports",
    summary="Every @path import in CLAUDE.md resolves to an existing file inside the repository.",
    why="A broken @import silently drops the referenced instructions from Claude Code's context.",
    fix="Correct or remove each @path import in CLAUDE.md so it points at an existing file "
        "inside the repository.",
    effort="mechanical",
)
def check_imports_resolve(index: ArtifactIndex):
    if index.claude_md is None:
        return None
    tokens = sorted(set(_IMPORT_RE.findall(index.claude_md.raw_text)))
    if not tokens:
        return None
    # Membership in the scanned snapshot, not a live filesystem probe: the
    # report must not depend on unscanned dirs or symlink targets (D3/D4).
    tree_files = {str(f) for f in index.tree.files} if index.tree is not None else set()
    ok = 0
    diags: list[tuple] = []
    for token in tokens:
        normalized = posixpath.normpath(token)
        if normalized.startswith(".."):
            reason = "escapes the repository root"
        elif normalized not in tree_files:
            reason = "does not exist in the scanned tree"
        else:
            ok += 1
            continue
        diags.append((index.claude_md_path, Diagnostic(
            rule_id="foundation.imports.resolve", severity=Severity.ERROR,
            message=f"CLAUDE.md imports '@{token}' but the target {reason}.",
        )))
    return (ok / len(tokens)), diags


@rule(
    id="foundation.entrypoint.parses", pillar=Pillar.FOUNDATION, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=2, severity=Severity.ERROR,
    source=RuleSource.SPEC,
    doc_url="https://code.visualstudio.com/docs/copilot/customization/custom-instructions",
    summary="Entry-point files decode as UTF-8 and any YAML frontmatter parses.",
    why="An entry point that fails to decode or parse is silently dropped or garbled "
        "when the assistant loads it.",
    fix="Re-save the entry point as UTF-8 and repair its YAML frontmatter fences.",
    effort="mechanical",
)
def check_entrypoint_parses(index: ArtifactIndex):
    entrypoints = [a for a in index.artifacts if a.kind in _ENTRYPOINT_KINDS]
    if not entrypoints:
        return None
    diags: list[tuple] = []
    for artifact in entrypoints:
        if artifact.parse_error is not None:
            diags.append((artifact.rel_path, Diagnostic(
                rule_id="foundation.entrypoint.parses", severity=Severity.ERROR,
                message=f"{artifact.rel_path} failed to parse: {artifact.parse_error}",
            )))
    if diags:
        return 0.0, diags
    return 1.0, []


# =============================================================================
# foundation.entrypoint.conditional-references (v0.3.0)
# =============================================================================

@rule(
    id="foundation.entrypoint.conditional-references", pillar=Pillar.FOUNDATION, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.INFO,
    source=RuleSource.ADVISORY,
    doc_url="https://www.humanlayer.dev/blog/writing-a-good-claude-md",
    summary="References to companion instruction docs use a load condition (when/if) "
            "rather than unconditionally inlining all detail.",
    why="Progressive disclosure applies to the entry point too: a reference with no load "
        "condition gets read eagerly every session or never, instead of only when relevant.",
    fix="Introduce each companion-doc reference with a condition, e.g. "
        "'Read docs/testing.md when writing new tests.'.",
    effort="authoring",
)
def check_entrypoint_conditional_references(index: ArtifactIndex):
    docs = _entrypoints(index)
    if not docs:
        return None
    paths = index.entrypoint_paths()
    total_refs = 0
    # Scored per entry point and averaged, like every other multi-document rule
    # here: a repo-wide "any entry point got it right" flag would let one
    # well-written CLAUDE.md hide the same problem in GEMINI.md and
    # copilot-instructions.md, and would discard their diagnostics.
    sats: list[float] = []
    diags: list[tuple] = []
    for doc, path in zip(docs, paths):
        refs = md.extract_references(doc.body)
        if not refs:
            continue
        total_refs += len(refs)
        lines = doc.body.splitlines()
        conditional = False
        for i, line in enumerate(lines):
            if not any(ref in line for ref in refs):
                continue
            window = lines[max(0, i - 1): i + 2]
            if any(md.LOAD_TRIGGER_RE.search(neighbor) for neighbor in window):
                conditional = True
                break
        sats.append(1.0 if conditional else 0.0)
        if not conditional:
            diags.append((path, Diagnostic(
                rule_id="foundation.entrypoint.conditional-references", severity=Severity.INFO,
                message=f"{doc.path.name} references {len(refs)} companion doc(s) but none is "
                        f"introduced with a load condition; tell the agent when to read each "
                        f"one (e.g. 'Read X when ...').",
            )))
    if total_refs < config.MIN_REFERENCES_FOR_CONDITIONAL_CHECK or not sats:
        return None  # N/A: nothing to gate
    return sum(sats) / len(sats), diags


# =============================================================================
# foundation.entrypoints.consistent (v0.3.1)
# =============================================================================

def _is_pure_bridge(doc: ParsedDocument) -> bool:
    """True when `doc.body`, with every `@path` import token stripped, has
    fewer than 40 non-whitespace characters left — i.e. it is a mirror
    (e.g. a CLAUDE.md that is just `@AGENTS.md`) rather than independent
    content that could meaningfully diverge from what it mirrors."""
    stripped = _IMPORT_RE.sub("", doc.body)
    non_whitespace = re.sub(r"\s+", "", stripped)
    return len(non_whitespace) < 40


def _consistency_candidates(index: ArtifactIndex) -> list[tuple[ParsedDocument, PurePosixPath]]:
    """Entry-point docs eligible for the divergence comparison: the always-on
    entry points plus the root AGENTS.md (nested AGENTS.md files are legitimately
    scoped differently and are excluded), minus pure bridges and near-empty stubs
    (both already penalized by other rules and carry no independent signal)."""
    candidates = list(zip(_entrypoints(index), index.entrypoint_paths()))
    for a in index.artifacts:
        if (a.kind == ArtifactKind.AGENTS_MD and a.rel_path == PurePosixPath("AGENTS.md")
                and a.doc is not None):
            candidates.append((a.doc, a.rel_path))
            break
    return [
        (doc, path) for doc, path in candidates
        if doc.line_count >= 5 and not _is_pure_bridge(doc)
    ]


@rule(
    id="foundation.entrypoints.consistent", pillar=Pillar.FOUNDATION, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.INFO,
    source=RuleSource.ADVISORY,
    doc_url="https://github.blog/ai-and-ml/github-copilot/5-tips-for-writing-better-custom-instructions-for-copilot/",
    summary="Multiple entry points (copilot-instructions.md, AGENTS.md, CLAUDE.md, GEMINI.md) "
            "cover the same core topics, rather than one being stale.",
    why="Repos with several instruction files risk one being updated while the others silently "
        "go stale, so different agents (Copilot vs Claude vs Gemini) end up with contradictory "
        "or incomplete context.",
    fix="Review the diverged files and either consolidate into a single AGENTS.md bridged to the "
        "others, or update the stale file to cover the missing topics.",
    effort="authoring",
)
def check_entrypoints_consistent(index: ArtifactIndex):
    candidates = _consistency_candidates(index)
    if len(candidates) < 2:
        return None  # N/A: single source of truth, or everything else is a bridge/stub
    signals = [_covered_signals(doc) for doc, _ in candidates]
    pairs = list(itertools.combinations(range(len(candidates)), 2))
    consistent = 0
    diags: list[tuple] = []
    for i, j in pairs:
        doc_i, path_i = candidates[i]
        doc_j, path_j = candidates[j]
        diff = signals[i] ^ signals[j]
        if len(diff) < 2:
            consistent += 1
            continue
        only_i = ", ".join(sorted(signals[i] - signals[j])) or "none"
        only_j = ", ".join(sorted(signals[j] - signals[i])) or "none"
        if doc_i is index.copilot_instructions:
            target_path = path_j
        elif doc_j is index.copilot_instructions:
            target_path = path_i
        else:
            target_path = max(path_i, path_j)
        diags.append((target_path, Diagnostic(
            rule_id="foundation.entrypoints.consistent", severity=Severity.INFO,
            message=f"{doc_i.path.name} and {doc_j.path.name} cover different topics "
                    f"({doc_i.path.name} only: {only_i}; {doc_j.path.name} only: {only_j}) "
                    f"— check whether one has gone stale.",
        )))
    return consistent / len(pairs), diags
