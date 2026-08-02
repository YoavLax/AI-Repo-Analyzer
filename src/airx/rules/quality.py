"""Quality pillar: how well entry-point and instructions files are written
(plan-v2-fable.md §4.3).

All nine rules operate on the entry-point documents
(`index.entrypoint_docs()`) plus parsed `*.instructions.md` artifacts
(`index.instructions`), except `quality.no-secrets`, which scans every
Markdown artifact in the repository. Multi-file rules aggregate by mean and
attach per-file diagnostics as `(rel_path, Diagnostic)` tuples.

A *directive* is a bulleted line (`^\\s*[-*]\\s+\\S`) with more than 10
visible (non-whitespace) characters, extracted from the body text after
fenced code blocks are stripped. Directive-based rules are not applicable
below `config.MIN_DIRECTIVES_FOR_QUALITY` directives per file
(`config.MIN_DIRECTIVES_FOR_EMPHASIS` for the emphasis rule).
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from airx import config
from airx.discovery import ArtifactIndex
from airx.model import Applicability, Diagnostic, ParsedDocument, Pillar, RuleSource, Severity
from airx.rules.registry import RuleScope, rule

# --- module-level compiled constants (determinism contract §0) ----------------

_DIRECTIVE_LINE_RE = re.compile(r"^\s*[-*]\s+\S")
_FENCE_LINE_RE = re.compile(r"^\s*(?:```|~~~)")
_MIN_DIRECTIVE_VISIBLE_CHARS = 10

# Concreteness signals (quality.specificity.index, spec §4.3).
_PATH_SHAPED_RE = re.compile(r"[\w./-]+\.[A-Za-z0-9]{1,8}|[\w./-]+/")
_UPPER_SNAKE_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
_DIGIT_RE = re.compile(r"\d")

_RATIONALE_RE = re.compile(
    r"\bbecause\b|\bsince\b|\bto avoid\b|\bso that\b|\botherwise\b|\bto ensure\b|\bto prevent\b",
    re.IGNORECASE,
)

_PREFERRED_PAIR_RES = (
    re.compile(r"\binstead of\b", re.IGNORECASE),
    re.compile(r"\bdon'?t\b[^\n]*\bdo\b", re.IGNORECASE),
    re.compile(r"\bprefer\b[^\n]*\bover\b", re.IGNORECASE),
)

# Case-sensitive by spec: only ALL-CAPS emphasis counts as emphasis inflation.
_EMPHASIS_RE = re.compile(r"\b(?:IMPORTANT|YOU MUST|ALWAYS|NEVER|CRITICAL)\b")


def _boundary_wrap(marker: str) -> str:
    pre = r"\b" if marker[0].isalnum() else ""
    post = r"\b" if marker[-1].isalnum() else ""
    return f"{pre}{re.escape(marker)}{post}"


_STALE_RES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (marker, re.compile(_boundary_wrap(marker), re.IGNORECASE))
    for marker in config.STALE_MARKERS
)

# Credential shapes are case-sensitive by construction (explicit character
# classes in each pattern), so no IGNORECASE here.
_SECRET_RES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p) for p in config.SECRET_SHAPE_PATTERNS
)

# Same link shape as airx.rules.skills: relative Markdown links only —
# http(s)/mailto URLs and pure `#anchor` links never match.
_MD_LINK_RE = re.compile(r"!?\[[^\]]*\]\((?!https?://|mailto:)([^)\s#]+)(?:#[^)]*)?\)")

_DOC_URL_WRITING = (
    "https://github.blog/ai-and-ml/github-copilot/"
    "5-tips-for-writing-better-custom-instructions-for-copilot/"
)


# --- shared extraction helpers ------------------------------------------------

@dataclass(frozen=True)
class _Directive:
    line: int  # 1-based line number in the raw file
    text: str  # full line text


def _strip_fences(body: str) -> tuple[list[str], int]:
    """Blank out fenced code-block content, preserving line positions.

    Returns the fence-stripped lines and the number of fenced blocks opened.
    """
    out: list[str] = []
    blocks = 0
    in_fence = False
    for line in body.splitlines():
        if _FENCE_LINE_RE.match(line):
            if not in_fence:
                blocks += 1
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return out, blocks


def _fenced_block_count(body: str) -> int:
    return _strip_fences(body)[1]


def _directives(doc: ParsedDocument) -> list[_Directive]:
    body_lines = doc.body.splitlines()
    offset = doc.line_count - len(body_lines)  # lines consumed by frontmatter
    stripped, _ = _strip_fences(doc.body)
    found: list[_Directive] = []
    for i, line in enumerate(stripped):
        if not _DIRECTIVE_LINE_RE.match(line):
            continue
        visible = sum(1 for c in line if not c.isspace())
        if visible > _MIN_DIRECTIVE_VISIBLE_CHARS:
            found.append(_Directive(line=offset + i + 1, text=line))
    return found


def _doc_rel_path(index: ArtifactIndex, doc: ParsedDocument) -> PurePosixPath:
    try:
        rel = Path(doc.path).resolve().relative_to(Path(index.root).resolve())
        return PurePosixPath(rel.as_posix())
    except ValueError:
        return PurePosixPath(doc.path.name)


def _quality_docs(index: ArtifactIndex) -> list[tuple[PurePosixPath, ParsedDocument]]:
    """Entry points plus parsed instructions files, sorted by relative path."""
    docs: list[tuple[PurePosixPath, ParsedDocument]] = []
    for doc in index.entrypoint_docs():
        docs.append((_doc_rel_path(index, doc), doc))
    for artifact in index.instructions:
        if artifact.doc is not None:
            docs.append((artifact.rel_path, artifact.doc))
    docs.sort(key=lambda item: str(item[0]))
    return docs


def _is_concrete(text: str) -> bool:
    return (
        "`" in text
        or _DIGIT_RE.search(text) is not None
        or _PATH_SHAPED_RE.search(text) is not None
        or _UPPER_SNAKE_RE.search(text) is not None
    )


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


# =============================================================================
# quality.specificity.index
# =============================================================================

@rule(
    id="quality.specificity.index", pillar=Pillar.QUALITY, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=6, severity=Severity.WARNING,
    source=RuleSource.ADVISORY, doc_url=_DOC_URL_WRITING,
    summary="Directives are concrete: they name commands, paths, numbers, or constants "
            "rather than generic advice.",
    why="Vague directives produce vague completions; concrete file names, commands, and "
        "numbers give the model something checkable to follow.",
    fix="Rewrite generic directives to name exact files, commands, or thresholds, "
        "using backticks for code and paths.",
    effort="authoring",
)
def check_specificity_index(index: ArtifactIndex):
    sats: list[float] = []
    diags: list[tuple[PurePosixPath, Diagnostic]] = []
    for rel, doc in _quality_docs(index):
        directives = _directives(doc)
        if len(directives) < config.MIN_DIRECTIVES_FOR_QUALITY:
            continue
        concrete = sum(1 for d in directives if _is_concrete(d.text))
        ratio = concrete / len(directives)
        sat = min(1.0, ratio / config.SPECIFICITY_TARGET)
        sats.append(sat)
        if sat < 1.0:
            diags.append((rel, Diagnostic(
                rule_id="quality.specificity.index", severity=Severity.WARNING,
                message=f"Only {concrete} of {len(directives)} directives are concrete "
                        f"(backticked code, a path, a number, or an UPPER_SNAKE constant); "
                        f"target is {config.SPECIFICITY_TARGET:.0%}.",
            )))
    if not sats:
        return None
    return sum(sats) / len(sats), diags


# =============================================================================
# quality.rationale.present
# =============================================================================

@rule(
    id="quality.rationale.present", pillar=Pillar.QUALITY, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=4, severity=Severity.WARNING,
    source=RuleSource.ADVISORY, doc_url=_DOC_URL_WRITING,
    summary="A share of directives explain why (because, to avoid, to ensure, ...).",
    why="Directives that carry a rationale are followed more reliably and generalize "
        "better than bare imperatives.",
    fix="Append a short reason ('because ...', 'to avoid ...') to the key directives.",
    effort="authoring",
)
def check_rationale_present(index: ArtifactIndex):
    sats: list[float] = []
    diags: list[tuple[PurePosixPath, Diagnostic]] = []
    for rel, doc in _quality_docs(index):
        directives = _directives(doc)
        if len(directives) < config.MIN_DIRECTIVES_FOR_QUALITY:
            continue
        with_rationale = sum(1 for d in directives if _RATIONALE_RE.search(d.text))
        ratio = with_rationale / len(directives)
        sat = min(1.0, ratio / config.RATIONALE_TARGET)
        sats.append(sat)
        if sat < 1.0:
            diags.append((rel, Diagnostic(
                rule_id="quality.rationale.present", severity=Severity.WARNING,
                message=f"Only {with_rationale} of {len(directives)} directives explain why "
                        f"(because/since/to avoid/so that/otherwise/to ensure/to prevent); "
                        f"target is {config.RATIONALE_TARGET:.0%}.",
            )))
    if not sats:
        return None
    return sum(sats) / len(sats), diags


# =============================================================================
# quality.examples.present
# =============================================================================

@rule(
    id="quality.examples.present", pillar=Pillar.QUALITY, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=4, severity=Severity.WARNING,
    source=RuleSource.ADVISORY, doc_url=_DOC_URL_WRITING,
    summary="Instructions include at least one fenced code example or a "
            "preferred/avoided pattern pair.",
    why="A single concrete example anchors ambiguous prose better than more prose.",
    fix="Add one fenced code block showing a preferred pattern, or an "
        "'instead of X, do Y' pair.",
    effort="additive",
)
def check_examples_present(index: ArtifactIndex):
    docs = _quality_docs(index)
    if not docs:
        return None
    for _rel, doc in docs:
        if _fenced_block_count(doc.body) >= 1:
            return 1.0, []
        if any(p.search(doc.body) for p in _PREFERRED_PAIR_RES):
            return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="quality.examples.present", severity=Severity.WARNING,
        message="No fenced code example or preferred/avoided pair ('instead of', "
                "\"don't ... do\", 'prefer ... over') found in entry-point or "
                "instructions files.",
    )]


# =============================================================================
# quality.no-obvious-rules
# =============================================================================

@rule(
    id="quality.no-obvious-rules", pillar=Pillar.QUALITY, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.INFO,
    source=RuleSource.ADVISORY, doc_url=_DOC_URL_WRITING,
    summary="Directives avoid generic truisms like 'write clean code' or "
            "'follow best practices'.",
    why="Truisms spend context tokens without changing model behavior.",
    fix="Delete generic truisms or replace each with a project-specific rule.",
    effort="mechanical",
)
def check_no_obvious_rules(index: ArtifactIndex):
    sats: list[float] = []
    diags: list[tuple[PurePosixPath, Diagnostic]] = []
    for rel, doc in _quality_docs(index):
        directives = _directives(doc)
        if len(directives) < config.MIN_DIRECTIVES_FOR_QUALITY:
            continue
        flagged = 0
        for d in directives:
            normalized = _normalize(d.text)
            hits = [p for p in config.OBVIOUS_RULES if p in normalized]
            if hits:
                flagged += 1
                diags.append((rel, Diagnostic(
                    rule_id="quality.no-obvious-rules", severity=Severity.INFO,
                    message=f"Directive states the obvious ('{hits[0]}'); replace it with "
                            f"a project-specific rule or remove it.",
                    line=d.line,
                )))
        sats.append(max(0.0, 1.0 - flagged / len(directives)))
    if not sats:
        return None
    return sum(sats) / len(sats), diags


# =============================================================================
# quality.directive.atomicity
# =============================================================================

@rule(
    id="quality.directive.atomicity", pillar=Pillar.QUALITY, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=2, severity=Severity.INFO,
    source=RuleSource.ADVISORY, doc_url=_DOC_URL_WRITING,
    summary=f"No directive exceeds {config.DIRECTIVE_MAX_CHARS} characters.",
    why="Long bullet items bundle several instructions and get partially followed.",
    fix="Split each long bullet into one directive per instruction.",
    effort="mechanical",
)
def check_directive_atomicity(index: ArtifactIndex):
    sats: list[float] = []
    diags: list[tuple[PurePosixPath, Diagnostic]] = []
    for rel, doc in _quality_docs(index):
        directives = _directives(doc)
        if len(directives) < config.MIN_DIRECTIVES_FOR_QUALITY:
            continue
        flagged = 0
        for d in directives:
            length = len(d.text.strip())
            if length > config.DIRECTIVE_MAX_CHARS:
                flagged += 1
                diags.append((rel, Diagnostic(
                    rule_id="quality.directive.atomicity", severity=Severity.INFO,
                    message=f"Directive is {length} characters "
                            f"(max {config.DIRECTIVE_MAX_CHARS}); split it into "
                            f"multiple bullets.",
                    line=d.line,
                )))
        sats.append(max(0.0, 1.0 - flagged / len(directives)))
    if not sats:
        return None
    return sum(sats) / len(sats), diags


# =============================================================================
# quality.emphasis.calibrated
# =============================================================================

@rule(
    id="quality.emphasis.calibrated", pillar=Pillar.QUALITY, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=2, severity=Severity.INFO,
    source=RuleSource.ADVISORY, doc_url=_DOC_URL_WRITING,
    summary="Uppercase emphasis (IMPORTANT, YOU MUST, ALWAYS, NEVER, CRITICAL) is used "
            "sparingly across directives.",
    why="When everything is IMPORTANT, nothing is; emphasis inflation erodes "
        "instruction-following.",
    fix="Reserve uppercase emphasis for the few rules that genuinely need it.",
    effort="mechanical",
)
def check_emphasis_calibrated(index: ArtifactIndex):
    sats: list[float] = []
    diags: list[tuple[PurePosixPath, Diagnostic]] = []
    for rel, doc in _quality_docs(index):
        directives = _directives(doc)
        if len(directives) < config.MIN_DIRECTIVES_FOR_EMPHASIS:
            continue
        emphasized = sum(1 for d in directives if _EMPHASIS_RE.search(d.text))
        ratio = emphasized / len(directives)
        if ratio > config.EMPHASIS_MAX_RATIO:
            sats.append(0.0)
            diags.append((rel, Diagnostic(
                rule_id="quality.emphasis.calibrated", severity=Severity.INFO,
                message=f"{emphasized} of {len(directives)} directives use uppercase "
                        f"emphasis tokens (over the {config.EMPHASIS_MAX_RATIO:.0%} "
                        f"calibration ceiling); demote most of them to plain wording.",
            )))
        else:
            sats.append(1.0)
    if not sats:
        return None
    return sum(sats) / len(sats), diags


# =============================================================================
# quality.no-stale-markers
# =============================================================================

@rule(
    id="quality.no-stale-markers", pillar=Pillar.QUALITY, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=2, severity=Severity.WARNING,
    source=RuleSource.ADVISORY, doc_url=_DOC_URL_WRITING,
    summary="No TODO/FIXME/TBD/XXX/placeholder/lorem-ipsum markers in instruction bodies.",
    why="Placeholder markers signal unfinished guidance that agents may follow literally.",
    fix="Resolve or remove TODO/FIXME/placeholder markers from instruction files.",
    effort="mechanical",
)
def check_no_stale_markers(index: ArtifactIndex):
    docs = _quality_docs(index)
    if not docs:
        return None
    diags: list[tuple[PurePosixPath, Diagnostic]] = []
    for rel, doc in docs:
        found = sorted({marker for marker, rx in _STALE_RES if rx.search(doc.body)})
        if found:
            diags.append((rel, Diagnostic(
                rule_id="quality.no-stale-markers", severity=Severity.WARNING,
                message=f"Stale marker(s) found: {', '.join(found)}. Finish or remove "
                        f"the placeholder content.",
            )))
    if diags:
        return 0.0, diags
    return 1.0, []


# =============================================================================
# quality.no-secrets
# =============================================================================

@rule(
    id="quality.no-secrets", pillar=Pillar.QUALITY, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=4, severity=Severity.ERROR,
    source=RuleSource.ADVISORY,  # allowlisted: shape-validated, objective check
    doc_url="https://cwe.mitre.org/data/definitions/798.html",
    summary="No credential-shaped string (GitHub/Anthropic/OpenAI/AWS/Slack/Google "
            "token or private key) appears in any AI artifact file.",
    why="Instruction files are loaded into every agent session and often mirrored to "
        "logs, so a credential here is effectively published.",
    fix="Remove the credential, rotate it, and reference it via an environment "
        "variable instead.",
    effort="mechanical",
)
def check_no_secrets(index: ArtifactIndex):
    # All Markdown artifacts. `index.skills` docs are SKILL-kind artifacts and
    # therefore already part of `index.artifacts`, so one pass covers both sets.
    scanned = sorted(
        ((a.rel_path, a.doc) for a in index.artifacts if a.doc is not None),
        key=lambda item: str(item[0]),
    )
    if not scanned:
        return None
    diags: list[tuple[PurePosixPath, Diagnostic]] = []
    for rel, doc in scanned:
        for line_no, line in enumerate(doc.raw_text.splitlines(), start=1):
            for rx in _SECRET_RES:
                match = rx.search(line)
                if match:
                    redacted = match.group()[:8] + "…"
                    diags.append((rel, Diagnostic(
                        rule_id="quality.no-secrets", severity=Severity.ERROR,
                        message=f"Credential-shaped string '{redacted}' matches secret "
                                f"pattern {rx.pattern!r}; remove and rotate it.",
                        line=line_no,
                    )))
    if diags:
        return 0.0, diags
    return 1.0, []


# =============================================================================
# quality.links.resolve
# =============================================================================

@rule(
    id="quality.links.resolve", pillar=Pillar.QUALITY, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.WARNING,
    source=RuleSource.ADVISORY,
    doc_url="https://code.visualstudio.com/docs/copilot/customization/custom-instructions",
    summary="Relative Markdown links in entry-point and instructions files resolve to "
            "files inside the repository.",
    why="Broken relative links send agents to files that do not exist, wasting tool "
        "calls and eroding trust in the instructions.",
    fix="Update or remove each relative link so its target exists inside the repository.",
    effort="mechanical",
)
def check_links_resolve(index: ArtifactIndex):
    # Resolve against the scanned snapshot, not the live filesystem: a link
    # into an unscanned dir (.git, node_modules) must produce the same report
    # whether or not that dir happens to exist on disk (D3/D4).
    tree_files = {str(f) for f in index.tree.files} if index.tree is not None else set()
    sats: list[float] = []
    diags: list[tuple[PurePosixPath, Diagnostic]] = []
    for rel, doc in _quality_docs(index):
        refs: list[str] = []
        for ref in _MD_LINK_RE.findall(doc.body):
            # Root-absolute links are not relative links; skip them.
            if not ref.startswith("/") and ref not in refs:
                refs.append(ref)
        if not refs:
            continue
        file_diags: list[Diagnostic] = []
        for ref in refs:
            target = posixpath.normpath(posixpath.join(posixpath.dirname(str(rel)), ref))
            # Agents (the audience this rule protects, per `why` above) almost
            # universally resolve paths mentioned in instructions relative to
            # the repository root via their file-access tools, not relative
            # to the directory of the instructions file that mentioned them
            # (unlike a browser resolving a rendered Markdown link's href).
            # Treat a link as resolved if it works under *either* reading, and
            # only report "escapes the repository root" when neither does and
            # the author's own text walks above root (leading `..`).
            root_relative_target = posixpath.normpath(ref)
            if target in tree_files or (not ref.startswith("..") and root_relative_target in tree_files):
                continue
            if target.startswith(".."):
                file_diags.append(Diagnostic(
                    rule_id="quality.links.resolve", severity=Severity.WARNING,
                    message=f"Relative link '{ref}' escapes the repository root.",
                ))
            else:
                file_diags.append(Diagnostic(
                    rule_id="quality.links.resolve", severity=Severity.WARNING,
                    message=f"Relative link '{ref}' does not resolve to a file in the scanned tree.",
                ))
        sats.append(1.0 if not file_diags else 0.0)
        diags.extend((rel, d) for d in file_diags)
    if not sats:
        return None
    return sum(sats) / len(sats), diags
