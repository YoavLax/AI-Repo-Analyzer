"""Locate AI-agent artifact files within a scanned repository tree."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from airx.fs import RepoTree
from airx.model import ParseError, ParsedDocument
from airx.parser import parse as parse_document


@dataclass(frozen=True)
class ArtifactIndex:
    root: Path
    skills: tuple[ParsedDocument, ...]
    skill_parse_errors: tuple[tuple[PurePosixPath, str], ...]
    copilot_instructions: ParsedDocument | None
    agents_md_paths: tuple[PurePosixPath, ...]
    claude_md: ParsedDocument | None
    claude_md_path: PurePosixPath | None


def _is_skill_file(rel: PurePosixPath) -> bool:
    if rel.name != "SKILL.md":
        return False
    parts = rel.parts
    # Matches `**/skills/<name>/SKILL.md` — the skills directory must be the
    # immediate grandparent, per the discovery patterns in plan.md section 5.1.
    return len(parts) >= 3 and parts[-3] == "skills"


def build_index(tree: RepoTree) -> ArtifactIndex:
    skills: list[ParsedDocument] = []
    skill_errors: list[tuple[PurePosixPath, str]] = []
    agents_md: list[PurePosixPath] = []
    copilot_instructions: ParsedDocument | None = None
    claude_md: ParsedDocument | None = None
    claude_md_path: PurePosixPath | None = None

    for rel in tree.files:
        abs_path = tree.root / Path(*rel.parts)

        if _is_skill_file(rel):
            try:
                skills.append(parse_document(abs_path))
            except ParseError as exc:
                skill_errors.append((rel, str(exc)))
            continue

        if rel == PurePosixPath(".github/copilot-instructions.md"):
            try:
                copilot_instructions = parse_document(abs_path)
            except ParseError:
                pass
            continue

        if rel.name == "AGENTS.md":
            agents_md.append(rel)
            continue

        if rel in (PurePosixPath("CLAUDE.md"), PurePosixPath(".claude/CLAUDE.md")):
            # Prefer the repo-root CLAUDE.md if both exist.
            if claude_md is None or rel == PurePosixPath("CLAUDE.md"):
                try:
                    claude_md = parse_document(abs_path)
                    claude_md_path = rel
                except ParseError:
                    pass
            continue

    skills.sort(key=lambda d: d.path.as_posix())
    return ArtifactIndex(
        root=tree.root,
        skills=tuple(skills),
        skill_parse_errors=tuple(sorted(skill_errors, key=lambda t: t[0].as_posix())),
        copilot_instructions=copilot_instructions,
        agents_md_paths=tuple(sorted(agents_md, key=lambda p: p.as_posix())),
        claude_md=claude_md,
        claude_md_path=claude_md_path,
    )
