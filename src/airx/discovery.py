"""Locate and classify AI-agent artifact files within a scanned repository tree.

Discovery walks the sorted file list once, classifies each path against the
declarative patterns in `airx.patterns`, parses what it can (Markdown via the
frontmatter parser, JSON artifacts via `json.loads`), and records parse
failures as data rather than raising — rules report them as findings.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from airx.fs import RepoTree
from airx.model import Artifact, ArtifactKind, ParseError, ParsedDocument, Platform
from airx.parser import parse as parse_document
from airx.patterns import classify
from airx.probe import RepoFacts, probe

_JSON_KINDS = frozenset({
    ArtifactKind.HOOKS,
    ArtifactKind.MCP,
    ArtifactKind.CLAUDE_SETTINGS,
    ArtifactKind.CLAUDE_SETTINGS_LOCAL,
})

# Kinds tracked by path only — their contents are never parsed (personal files
# whose mere presence in the tree is what rules care about).
_PATH_ONLY_KINDS = frozenset({
    ArtifactKind.CLAUDE_SETTINGS_LOCAL,
    ArtifactKind.CLAUDE_LOCAL_MD,
})


@dataclass(frozen=True)
class ArtifactIndex:
    root: Path
    # --- v0.1.0 fields (kept verbatim for compatibility) ---------------------
    skills: tuple[ParsedDocument, ...]
    skill_parse_errors: tuple[tuple[PurePosixPath, str], ...]
    copilot_instructions: ParsedDocument | None
    agents_md_paths: tuple[PurePosixPath, ...]
    claude_md: ParsedDocument | None
    claude_md_path: PurePosixPath | None
    # --- v0.2.0 additions ----------------------------------------------------
    artifacts: tuple[Artifact, ...] = ()
    instructions: tuple[Artifact, ...] = ()
    prompts: tuple[Artifact, ...] = ()
    agents: tuple[Artifact, ...] = ()
    claude_rules: tuple[Artifact, ...] = ()
    hooks: tuple[Artifact, ...] = ()
    mcp: tuple[Artifact, ...] = ()
    claude_settings: Artifact | None = None
    claude_settings_local_paths: tuple[PurePosixPath, ...] = ()
    claude_local_md_paths: tuple[PurePosixPath, ...] = ()
    agents_md_nested: tuple[PurePosixPath, ...] = ()
    tree: RepoTree | None = None
    facts: RepoFacts | None = None

    def entrypoint_docs(self) -> tuple[ParsedDocument, ...]:
        """The always-on entry points that exist, in stable order."""
        return tuple(d for d in (self.copilot_instructions, self.claude_md) if d is not None)

    def entrypoint_paths(self) -> tuple[PurePosixPath, ...]:
        """Relative paths for `entrypoint_docs()`, in the same order (for
        diagnostics that must point back at the file to edit)."""
        paths: list[PurePosixPath] = []
        if self.copilot_instructions is not None:
            for a in self.artifacts:
                if a.kind == ArtifactKind.ENTRYPOINT_COPILOT and a.doc is self.copilot_instructions:
                    paths.append(a.rel_path)
                    break
        if self.claude_md is not None and self.claude_md_path is not None:
            paths.append(self.claude_md_path)
        return tuple(paths)


def _error_text(exc: Exception) -> str:
    """Stringify a read/parse failure WITHOUT the absolute path (OSError's str
    embeds it), so the checkout location never leaks into report output."""
    if isinstance(exc, OSError):
        return f"{type(exc).__name__}: {exc.strerror or 'unreadable'}"
    return str(exc)


def _make_artifact(root: Path, rel: PurePosixPath, kind: ArtifactKind, platform: Platform) -> Artifact:
    abs_path = root / str(rel)

    if kind in _PATH_ONLY_KINDS:
        return Artifact(kind=kind, rel_path=rel, platform=platform)

    if kind in _JSON_KINDS:
        json_data: Any | None = None
        parse_error: str | None = None
        try:
            json_data = json.loads(abs_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            parse_error = _error_text(exc)
        return Artifact(kind=kind, rel_path=rel, platform=platform,
                        json_data=json_data, parse_error=parse_error)

    doc: ParsedDocument | None = None
    parse_error = None
    try:
        doc = parse_document(abs_path)
    except (ParseError, OSError) as exc:
        # OSError too: an unreadable Markdown artifact must degrade to a
        # parse_error finding, not abort the whole analysis (exit 3).
        parse_error = _error_text(exc)
    return Artifact(kind=kind, rel_path=rel, platform=platform,
                    doc=doc, parse_error=parse_error)


def build_index(tree: RepoTree) -> ArtifactIndex:
    artifacts: list[Artifact] = []
    by_kind: dict[ArtifactKind, list[Artifact]] = {kind: [] for kind in ArtifactKind}

    for rel in tree.files:
        classified = classify(rel)
        if classified is None:
            continue
        kind, platform = classified
        artifact = _make_artifact(tree.root, rel, kind, platform)
        artifacts.append(artifact)
        by_kind[kind].append(artifact)

    # --- v0.1.0-compatible views --------------------------------------------
    skills = tuple(a.doc for a in by_kind[ArtifactKind.SKILL] if a.doc is not None)
    skill_parse_errors = tuple(
        (a.rel_path, a.parse_error)
        for a in by_kind[ArtifactKind.SKILL]
        if a.parse_error is not None
    )

    copilot = by_kind[ArtifactKind.ENTRYPOINT_COPILOT]
    copilot_instructions = copilot[0].doc if copilot else None

    claude_md: ParsedDocument | None = None
    claude_md_path: PurePosixPath | None = None
    for a in by_kind[ArtifactKind.ENTRYPOINT_CLAUDE]:
        # Prefer the repo-root CLAUDE.md if both exist.
        if a.doc is not None and (claude_md is None or a.rel_path == PurePosixPath("CLAUDE.md")):
            claude_md = a.doc
            claude_md_path = a.rel_path

    agents_md_paths = tuple(a.rel_path for a in by_kind[ArtifactKind.AGENTS_MD])
    agents_md_nested = tuple(p for p in agents_md_paths if len(p.parts) > 1)

    settings = by_kind[ArtifactKind.CLAUDE_SETTINGS]

    return ArtifactIndex(
        root=tree.root,
        skills=skills,
        skill_parse_errors=skill_parse_errors,
        copilot_instructions=copilot_instructions,
        agents_md_paths=agents_md_paths,
        claude_md=claude_md,
        claude_md_path=claude_md_path,
        artifacts=tuple(artifacts),
        instructions=tuple(by_kind[ArtifactKind.INSTRUCTIONS]),
        prompts=tuple(by_kind[ArtifactKind.PROMPT]),
        agents=tuple(by_kind[ArtifactKind.AGENT]),
        claude_rules=tuple(by_kind[ArtifactKind.CLAUDE_RULE]),
        hooks=tuple(by_kind[ArtifactKind.HOOKS]),
        mcp=tuple(by_kind[ArtifactKind.MCP]),
        claude_settings=settings[0] if settings else None,
        claude_settings_local_paths=tuple(
            a.rel_path for a in by_kind[ArtifactKind.CLAUDE_SETTINGS_LOCAL]
        ),
        claude_local_md_paths=tuple(
            a.rel_path for a in by_kind[ArtifactKind.CLAUDE_LOCAL_MD]
        ),
        agents_md_nested=agents_md_nested,
        tree=tree,
        facts=probe(tree),
    )
