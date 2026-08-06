"""Scoping pillar: path-scoped instruction files and their `applyTo` globs.

Corresponds to plan-v2-fable.md §4.4. "Scoped files" are the artifacts that
carry path- or area-limited guidance instead of always-on context:
`.github/instructions/**/*.instructions.md`, `.claude/rules/**/*.md`, and any
`AGENTS.md` below the repository root (`index.instructions`,
`index.claude_rules`, `index.agents_md_nested`).

Glob semantics (own translation, documented here per §4.4): an `applyTo`
frontmatter value is either a single string (possibly comma-separated globs)
or a YAML list of strings. Each glob is translated to a regular expression
with exactly three wildcard forms:

    ``**`` -> ``.*``      (matches anything, crossing ``/`` separators)
    ``*``  -> ``[^/]*``   (matches within a single path segment)
    ``?``  -> ``[^/]``    (matches one non-separator character)

Every other character is escaped literally, and the result is anchored to the
full POSIX-normalized repo-relative path (``re.fullmatch``), so ``src`` does
not match ``src/app.py``. A pattern "matches the tree" when at least one file
in ``index.tree.files`` matches.
"""
from __future__ import annotations

import functools
import re
from typing import Any, Mapping

from airx import config
from airx.discovery import ArtifactIndex
from airx.model import Applicability, Diagnostic, Pillar, Platform, RuleSource, Severity
from airx.rules.registry import RuleScope, rule

_DOC_URL_INSTRUCTIONS = "https://code.visualstudio.com/docs/copilot/customization/custom-instructions"
_DOC_URL_MEMORY = "https://code.claude.com/docs/en/memory#write-effective-instructions"

#: The universal glob: applies an instructions file to every path in the tree.
_UNIVERSAL_GLOB = "**"

_SCOPED_HINT = (
    ".github/instructions/*.instructions.md, .claude/rules/*.md, or a nested AGENTS.md"
)


def _scoped_file_count(index: ArtifactIndex) -> int:
    """Number of path-scoped instruction artifacts (plan-v2-fable.md §4.4)."""
    return len(index.instructions) + len(index.claude_rules) + len(index.agents_md_nested)


def _applyto_globs(frontmatter: Mapping[str, Any]) -> tuple[str, ...]:
    """Extract the `applyTo` globs from instructions-file frontmatter.

    Accepts a string (split on commas) or a YAML list of strings; anything
    else — including a missing key — yields no globs. Order is the
    declaration order in the file, so results stay deterministic.
    """
    value = frontmatter.get("applyTo")
    if isinstance(value, str):
        return tuple(g.strip() for g in value.split(",") if g.strip())
    if isinstance(value, list):
        return tuple(g.strip() for g in value if isinstance(g, str) and g.strip())
    return ()


@functools.lru_cache(maxsize=None)
def _glob_regex(pattern: str) -> re.Pattern[str]:
    """Compile one glob to an anchored regex (translation documented above)."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            if pattern[i : i + 3] == "**/" and (i == 0 or pattern[i - 1] == "/"):
                # A `**/` segment may match zero directories: '**/*.py' must
                # match both 'x.py' and 'src/x.py', 'a/**/b' must match 'a/b'.
                out.append("(?:.*/)?")
                i += 3
            elif pattern[i : i + 2] == "**":
                out.append(".*")
                i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    return re.compile("".join(out))


def _glob_match(pattern: str, path_str: str) -> bool:
    """True when `pattern` fully matches the POSIX-relative `path_str`.

    Wildcards: `**` crosses directory separators, `*` stays within one path
    segment, `?` matches one non-separator character; the match is anchored
    at both ends (`re.fullmatch`).
    """
    return _glob_regex(pattern).fullmatch(path_str) is not None


@rule(
    id="scoping.scoped-files.present", pillar=Pillar.SCOPING, scope=RuleScope.REPO,
    applicability=Applicability.PRESENCE, weight=8, severity=Severity.WARNING,
    source=RuleSource.ADVISORY, doc_url=_DOC_URL_INSTRUCTIONS,
    summary="At least one path-scoped instruction file exists "
            "(*.instructions.md, .claude/rules/*.md, or a nested AGENTS.md).",
    why="Path-scoped instructions keep guidance next to the code it governs instead of "
        "bloating the always-on entry point.",
    fix="Add a .github/instructions/<area>.instructions.md, a .claude/rules/<topic>.md, "
        "or an AGENTS.md inside a subsystem directory.",
    fix_by_platform=(
        (Platform.COPILOT, "Add a .github/instructions/<area>.instructions.md or an AGENTS.md "
                            "inside a subsystem directory."),
        (Platform.CLAUDE, "Add a .claude/rules/<topic>.md or an AGENTS.md inside a subsystem directory."),
    ),
    effort="additive",
)
def check_scoped_files_present(index: ArtifactIndex):
    if _scoped_file_count(index) >= 1:
        return 1.0, []
    return 0.0, [Diagnostic(
        rule_id="scoping.scoped-files.present", severity=Severity.WARNING,
        message=f"No path-scoped instruction files found ({_SCOPED_HINT}).",
    )]


@rule(
    id="scoping.instructions.parses", pillar=Pillar.SCOPING, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=4, severity=Severity.ERROR,
    source=RuleSource.SPEC, doc_url=_DOC_URL_INSTRUCTIONS,
    platforms=(Platform.COPILOT,),
    why="An instructions file whose frontmatter does not parse cannot be loaded, "
        "so none of its guidance ever reaches the assistant.",
    fix="Repair the YAML frontmatter fences in the .instructions.md file so the file parses.",
    effort="mechanical",
    summary="Every *.instructions.md decodes and its YAML frontmatter parses.",
    spec_quote="Instructions files are Markdown files with the `.instructions.md` extension. "
               "The optional YAML frontmatter header controls when the instructions are applied",
)
def check_instructions_parses(index: ArtifactIndex):
    # Contents rule: only instructions files whose bytes are in this snapshot.
    instructions = index.analyzed(index.instructions)
    if not instructions:
        return None  # N/A: no instructions files
    sats: list[float] = []
    diags: list[tuple] = []
    for a in instructions:  # sorted by rel_path (discovery order)
        if a.doc is None:
            sats.append(0.0)
            diags.append((a.rel_path, Diagnostic(
                rule_id="scoping.instructions.parses", severity=Severity.ERROR,
                message=f"{a.rel_path.name} failed to parse: {a.parse_error}",
            )))
        else:
            sats.append(1.0)
    return sum(sats) / len(sats), diags


@rule(
    id="scoping.applyto.declared", pillar=Pillar.SCOPING, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.INFO,
    source=RuleSource.ADVISORY, doc_url=_DOC_URL_INSTRUCTIONS,
    platforms=(Platform.COPILOT,),
    why="Without applyTo the file is opt-in: it reaches the model only when someone "
        "attaches it to a request by hand.",
    fix="If the instructions are meant to load on their own, add an applyTo glob; "
        "if they are a manual attachment, no change is needed.",
    effort="mechanical",
    summary="Every *.instructions.md declares a non-empty applyTo frontmatter scope.",
)
def check_applyto_declared(index: ArtifactIndex):
    """Auto-apply coverage, at INFO.

    This was a SPEC-sourced ERROR at weight 6 until the page it cites was
    actually read. VS Code lists `applyTo` as Required: No and documents the
    omitted case as a working configuration: "If not specified, the
    instructions are not applied automatically, but you can still add them
    manually to a chat request." A repository that ships manually-attached
    instruction sets is following the documentation, and was being handed an
    error that capped its grade for it.

    The parse-failure branch that used to live here moved to
    `scoping.instructions.parses`, where an ERROR is still the honest severity.
    """
    # Contents rule: an instructions file whose bytes are outside this snapshot
    # cannot be said to lack applyTo — nobody looked.
    instructions = [a for a in index.analyzed(index.instructions) if a.doc is not None]
    if not instructions:
        return None  # N/A: no parseable instructions files to scope
    sats: list[float] = []
    diags: list[tuple] = []
    for a in instructions:  # sorted by rel_path (discovery order)
        if _applyto_globs(a.doc.frontmatter):
            sats.append(1.0)
        else:
            sats.append(0.0)
            diags.append((a.rel_path, Diagnostic(
                rule_id="scoping.applyto.declared", severity=Severity.INFO,
                message=f"{a.rel_path.name} declares no applyTo glob, so it never loads "
                        f"automatically; it applies only when attached to a request by hand.",
            )))
    return sum(sats) / len(sats), diags


@rule(
    id="scoping.applyto.matches", pillar=Pillar.SCOPING, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=4, severity=Severity.WARNING,
    source=RuleSource.ADVISORY, doc_url=_DOC_URL_INSTRUCTIONS,
    platforms=(Platform.COPILOT,),
    why="An applyTo glob that matches nothing means the instructions silently never load.",
    fix="Correct the applyTo glob so it matches at least one file in the repository.",
    effort="mechanical",
    summary="Each applyTo glob matches at least one file in the repository tree.",
)
def check_applyto_matches(index: ArtifactIndex):
    per_file: list[tuple[Any, tuple[str, ...]]] = []
    for a in index.instructions:  # sorted by rel_path
        globs = _applyto_globs(a.doc.frontmatter) if a.doc is not None else ()
        if globs:
            per_file.append((a.rel_path, globs))
    if not per_file:
        return None  # N/A: no instructions file declares any applyTo glob
    tree_paths = tuple(p.as_posix() for p in index.tree.files) if index.tree else ()
    sats: list[float] = []
    diags: list[tuple] = []
    for rel_path, globs in per_file:
        matched = 0
        for glob in globs:
            if any(_glob_match(glob, p) for p in tree_paths):
                matched += 1
            else:
                diags.append((rel_path, Diagnostic(
                    rule_id="scoping.applyto.matches", severity=Severity.WARNING,
                    message=f"applyTo glob {glob!r} matches no file in the repository tree.",
                )))
        sats.append(matched / len(globs))
    return sum(sats) / len(sats), diags


@rule(
    id="scoping.applyto.not-universal", pillar=Pillar.SCOPING, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=3, severity=Severity.INFO,
    source=RuleSource.ADVISORY, doc_url=_DOC_URL_INSTRUCTIONS,
    platforms=(Platform.COPILOT,),
    why="Multiple universal '**' scopes duplicate the always-on entry point instead of "
        "scoping guidance to the paths it governs.",
    fix="Narrow the applyTo globs of the extra universally-scoped instructions files, or "
        "merge their content into the entry point.",
    effort="mechanical",
    summary="At most one instructions file uses the universal applyTo scope '**'.",
)
def check_applyto_not_universal(index: ArtifactIndex):
    if not index.instructions:
        return None  # N/A: no instructions files
    universal = []  # rel_paths of files carrying an applyTo glob == '**', sorted
    for a in index.instructions:  # sorted by rel_path
        globs = _applyto_globs(a.doc.frontmatter) if a.doc is not None else ()
        if any(g == _UNIVERSAL_GLOB for g in globs):
            universal.append(a.rel_path)
    if len(universal) <= 1:
        return 1.0, []
    diags = [
        (p, Diagnostic(
            rule_id="scoping.applyto.not-universal", severity=Severity.INFO,
            message=f"applyTo '**' here is universal; {universal[0].as_posix()} already "
                    f"covers every file — narrow this scope.",
        ))
        for p in universal[1:]
    ]
    return 0.0, diags


@rule(
    id="scoping.monolith", pillar=Pillar.SCOPING, scope=RuleScope.REPO,
    applicability=Applicability.QUALITY, weight=5, severity=Severity.WARNING,
    source=RuleSource.ADVISORY, doc_url=_DOC_URL_MEMORY,
    why="A monolithic entry point dilutes instruction adherence when nothing is delegated "
        "to path-scoped files.",
    fix="Move path- or topic-specific guidance from the entry point into scoped "
        "instruction files.",
    effort="authoring",
    summary="A long entry point (> 250 lines) is accompanied by path-scoped instruction files.",
)
def check_monolith(index: ArtifactIndex):
    docs = index.entrypoint_docs()
    if not docs:
        return None  # N/A: no entry point
    offenders = [d for d in docs if d.line_count > config.MONOLITH_LINES]
    if offenders and _scoped_file_count(index) == 0:
        diags = [Diagnostic(
            rule_id="scoping.monolith", severity=Severity.WARNING,
            message=f"{d.path.name} is {d.line_count} lines (> {config.MONOLITH_LINES}) with "
                    f"no path-scoped instruction files; split guidance into {_SCOPED_HINT}.",
        ) for d in offenders]
        return 0.0, diags
    return 1.0, []
